# Modificações aplicadas a este fork do pyfhirsdc

Fork de origem: https://github.com/SwissTPH/pyfhirsdc (branch `develop`)
Repositório deste fork: `cesaraugustomt/pyfhirsdc`
Contexto: trabalho de mestrado (PPGINFOS/UFSC) — Mini-DAK de Telemonitoramento
da Hipertensão Arterial (HTA). O conteúdo do Mini-DAK (planilhas, docx, BPMN)
**não faz parte deste repositório** e nunca foi copiado para dentro dele — ele
é mantido separadamente (pasta `DAK/` do projeto do mestrado) e é referenciado
apenas por caminho de arquivo em um arquivo de configuração externo a este
repositório (`conf-hta.json`), seguindo exatamente o mesmo padrão que o
pyfhirsdc já usa para `data_dictionary_file` e `decision_support_logic_file`.

## Por que modificar o pyfhirsdc em vez de usá-lo sem alterações

O pipeline principal do pyfhirsdc (flag `-o`) gera recursos FHIR (Questionnaire,
PlanDefinition, ValueSet, CodeSystem, Condition, ActivityDefinition) a partir
de um `inputFile` com um schema próprio (abas `pd.`, `q.`, `valueSet`, `profile`,
`c.`, `l.`, `r.`), no qual a lógica de decisão é representada como uma **árvore
de ações pai/filho** (`PlanDefinitionAction` ligado por `parentId`).

O Mini-DAK HTA segue o template oficial WHO SMART Guidelines L2, no qual a
lógica de decisão é representada como **tabela de regras no formato DMN**
(colunas de entrada/saída, política de avaliação Unique/First/Rule order, AND
dentro da linha e OR entre linhas). Os dois modelos não são equivalentes —
não é uma questão de renomear colunas, e sim de dois modelos de dados
distintos para lógica de decisão. Reescrever esse tradutor DMN → árvore de
ações está fora do escopo deste trabalho.

Optamos, portanto, por estender o pyfhirsdc com um caminho de processamento
adicional que opera **diretamente sobre o data dictionary no formato oficial
L2** (que o pyfhirsdc já sabe localizar via a chave de configuração existente
`data_dictionary_file`), reaproveitando a mesma stack de dependências do
projeto (principalmente `fhir.resources`) para produzir:

1. Uma matriz de interoperabilidade consolidada (o dicionário de dados já traz,
   por elemento, mapeamentos para CID-10, CID-11, LOINC, SNOMED CT, ATC, ICHI
   e CIF/ICF, mas espalhados em 47 colunas por aba — este módulo os consolida
   em uma tabela legível).
2. Recursos FHIR de nível L3: um `CodeSystem` local para os IDs de elemento de
   dado, um `ConceptMap` ligando esses IDs aos códigos padrão, e exemplos de
   instância FHIR — todos validados estruturalmente pela biblioteca
   `fhir.resources`.

## Arquivos adicionados

- `pyfhirsdc/services/generateInteropMatrix.py` (novo)
  Contém toda a lógica: detecção automática das abas de processo de negócio
  no data dictionary (pela presença da coluna obrigatória do template oficial
  `"ID do elemento de dado*"`, não por nomes de aba fixos — permitindo reuso
  em outros Mini-DAKs sem alterar o código), extração dos mapeamentos de
  terminologia, geração da matriz (xlsx + markdown) e geração do `CodeSystem`
  + `ConceptMap` + exemplos de instância FHIR via `fhir.resources`.
  Ponto de entrada: `process_interop_matrix(conf=None)`.

- `conf-hta.json` (novo)
  Arquivo de configuração específico para rodar o pipeline contra o Mini-DAK
  HTA. Contém **apenas caminhos de arquivo** para fora do repositório
  (pasta `DAK/` do projeto do mestrado) — nenhum conteúdo do Mini-DAK está
  copiado neste arquivo ou em qualquer outro lugar do fork.

## Arquivos modificados

- `main.py`
  - Import de `process_interop_matrix` (novo).
  - Nova flag de linha de comando `-m` / `--matrix`.
  - Novo bloco `if matrix: process_interop_matrix(conf)`.
  - Nenhuma linha do fluxo original (`-o`, `-b`, `-l`, `-u`) foi alterada ou
    removida — a modificação é estritamente aditiva.
  - Diff completo em `main.py.diff` (gerado com `diff -u main.py.bak-original main.py`).
    Backup do arquivo original preservado em `main.py.bak-original`.

Nenhum outro arquivo do pyfhirsdc original foi alterado.

## Ambiente de execução — incompatibilidade de dependências encontrada e corrigida

O `pyproject.toml` original declara `fhir.resources>=7.0.2` sem limite
superior. Instalar as dependências "soltas" (sem passar por `pip install .`)
resolve, hoje, para `fhir.resources` 8.x, que usa **Pydantic v2**. Porém o
código nativo do pyfhirsdc (ex.: `pyfhirsdc/models/questionnaireSDC.py`) usa
diretamente a API interna do **Pydantic v1** (`from pydantic.types import
StrBytes`), removida no v2. Isso faz `main.py` falhar já na importação,
**independente de qualquer flag usada** (`-o`, `-m` etc.) — ou seja, é uma
incompatibilidade pré-existente do fork com ambientes Python atuais, não
introduzida por esta modificação.

Correção aplicada (ambiente local, não é uma alteração de código-fonte):
fixar a versão do Pydantic para a série 1.x, compatível com o que o código
do pyfhirsdc espera:

```bash
pip install "pydantic<2" "fhir.resources==7.0.2"
```

Além disso, o pyfhirsdc precisa estar instalado como pacote (não basta ter
as dependências no `PYTHONPATH`), pois `pyfhirsdc/version.py` lê a própria
versão via `importlib.metadata`, que falha se o pacote não estiver
registrado:

```bash
pip install --no-deps -e .
```

(`--no-deps` evita que essa instalação reintroduza o conflito de versão do
`fhir.resources`/Pydantic acima.)

Versões testadas e validadas nesta modificação:
- Python 3.10.12
- pydantic==1.10.26
- fhir.resources==7.0.2
- pandas, openpyxl (já exigidos pelo projeto original)

## Versão 2 (v2) do `generateInteropMatrix.py` — correções e extensões

Após uma primeira execução completa (v1) e uma revisão crítica dos artefatos
gerados, foram identificados três problemas concretos, todos corrigidos nesta
segunda versão do módulo (o arquivo v1 foi preservado como
`generateInteropMatrix.py.bak-v1` para referência/comparação no relatório).

### v2.1 — Bug: `canonicalBase` nunca era lido da configuração

**Sintoma:** o `ConceptMap` gerado sempre apresentava
`url: "http://example.org/fhir/ConceptMap/..."`, mesmo com
`fhir.canonicalBase` corretamente definido como
`"http://mini-dak-hta.example.org/fhir/"` em `conf-hta.json`.

**Causa raiz:** em `process_interop_matrix()`, a v1 tentava ler o
`canonicalBase` assim:

```python
cfg = get_processor_cfg()
canonical_base = getattr(getattr(cfg, "fhir", None), "canonicalBase", None) or "http://example.org/fhir/"
```

`get_processor_cfg()` retorna apenas o objeto `processor` da configuração
(ver `pyfhirsdc/config.py`) — ele nunca teve um atributo `fhir`. Esse
`getattr` encadeado, portanto, sempre resolvia para `None` e caía
silenciosamente no valor padrão, sem gerar nenhum erro ou aviso.

**Correção:** usar `get_fhir_cfg()`, a função já existente em
`pyfhirsdc/config.py` especificamente para o objeto `fhir` da configuração:

```python
fhir_cfg = get_fhir_cfg()
canonical_base = getattr(fhir_cfg, "canonicalBase", None) or "http://example.org/fhir/"
```

**Verificação:** reexecutado com `conf-hta.json` (canonicalBase =
`http://mini-dak-hta.example.org/fhir/`); confirmado que tanto o `CodeSystem`
quanto o `ConceptMap` gerados agora usam essa base em seus campos `url`.

### v2.2 — Lacuna: `ConceptMap.group[].source` referenciava um CodeSystem inexistente

**Sintoma:** o `ConceptMap` da v1 declarava, em cada grupo,
`"source": "<canonicalBase>CodeSystem/dak-data-elements"` — mas nenhum
recurso `CodeSystem` com esse `url` era de fato gerado. Do ponto de vista de
validação estrutural de um Implementation Guide FHIR, isso é uma referência
solta (dangling reference).

**Correção:** nova função `build_codesystem(records, canonical_base)`, que
gera um `CodeSystem` FHIR (`id: dak-data-elements`, `content: complete`) com
um `concept` para cada elemento de dado do dicionário (código = ID do
elemento, display = nome do elemento, definition = descrição). Escrito em
`CodeSystem-dak-data-elements.json`, gerado antes do `ConceptMap` em
`process_interop_matrix()`.

### v2.3 — Cobertura incompleta dos exemplos de instância FHIR

**Sintoma:** a v1 gerava exatamente 2 exemplos (`Observation`, `Condition`),
com um `break` explícito logo após o primeiro elemento correspondente — apesar
de a heurística `suggest_fhir()` sugerir 7 tipos de recurso distintos ao
todo (Patient, Condition, Appointment, Observation, MedicationStatement,
Flag, CommunicationRequest, além de Identifier/Practitioner como anotações
de campo, não recursos autônomos).

**Correção:** `build_example_resources()` foi reescrita para gerar **um
exemplo por tipo de recurso sugerido** (7/7), mantendo a mesma filosofia de
genericidade do resto do módulo — os exemplos são escolhidos por *tipo de
recurso sugerido pela heurística*, não por ID de elemento fixo, então a
função continua funcionando sem alteração de código em outro Mini-DAK que
use o mesmo template L2. Cada tipo tem seu próprio bloco `try/except`, para
que a falha ao montar um tipo não impeça a geração dos demais (na v1, uma
falha em qualquer parte de `build_example_resources()` descartava todos os
exemplos, pois o `try/except` estava só em `process_interop_matrix()`).

Detalhes de modelagem específicos de cada novo exemplo (registrados aqui
porque envolveram decisões de projeto, não são triviais):

- **Patient**: como o dicionário de dados representa "identificação",
  "nome" e "data de nascimento" como três elementos de dado separados (na
  mesma atividade `HTA.A1`), o gerador os combina em um único recurso
  `Patient` de exemplo, associando cada elemento ao campo FHIR correspondente
  (`identifier`, `name`, `birthDate`) por correspondência de padrão no nome
  do elemento — e não por ID fixo. **Limitação registrada, não corrigida
  automaticamente:** o dicionário de dados não especifica qual
  OID/URI oficial (ex.: o identificador do CNS no padrão RNDS) deveria ser
  usado como `Identifier.system`; o exemplo usa um `NamingSystem` local
  provisório sob o `canonicalBase` do projeto, a ser confirmado com uma
  eventual integração real com a RNDS.
- **Appointment**: combina os elementos "periodicidade do ciclo" e "data do
  próximo ciclo" (atividades `HTA.A3` e `HTA.E2`) em um único exemplo,
  usando `Appointment.comment` para registrar a periodicidade (que não tem
  uma correspondência direta e óbvia em nenhum campo estruturado de
  `Appointment` para "intervalo entre agendamentos recorrentes").
- **MedicationStatement**: o elemento "Adesão à medicação no período"
  (`HTA.B4.DE1`) já tem, no dicionário de dados, mapeamentos para SNOMED CT
  (266710000, *Drug compliance*) e CID-10 (Z91.14, *Não adesão a regime
  medicamentoso*). Esses códigos descrevem o **conceito de adesão/não-adesão
  em si**, não o medicamento sendo tomado — por isso não fazem sentido em
  `MedicationStatement.medicationCodeableConcept` (que deveria descrever o
  fármaco). **Achado metodológico registrado no exemplo, não resolvido
  silenciosamente:** o recurso `MedicationStatement` do FHIR R4/R4B não tem
  um elemento estruturado dedicado a "grau de adesão"; o exemplo gerado usa
  `status: unknown` (neutro, não afirma nada sobre um paciente real) e anota
  os códigos mapeados em `MedicationStatement.note`, com um texto explicando
  essa limitação — uma alternativa mais aderente ao padrão internacional
  seria modelar a adesão como uma `Observation` com um LOINC de
  autorrelato de adesão, o que exigiria revisar o mapeamento de recurso
  sugerido para esse elemento (fora do escopo desta correção pontual).
- **Flag** e **CommunicationRequest**: os elementos correspondentes
  (`HTA.C4.DE2`, `HTA.D2.DE1`) não têm nenhum código de terminologia mapeado
  no dicionário de dados — os exemplos usam `CodeableConcept.text` (texto
  livre), sem `coding`, o que é FHIR-válido mas reflete fielmente que esses
  elementos ainda não têm ligação com uma terminologia padrão.

**Verificação:** reexecutado com `conf-hta.json` contra o Mini-DAK real;
log confirma `7/7 tipo(s) de recurso com exemplo gerado`, e cada um dos 7
arquivos JSON foi validado estruturalmente pela biblioteca `fhir.resources`
ao ser construído (uma instanciação inválida levantaria uma exceção do
Pydantic antes mesmo da escrita do arquivo).

### Backups desta revisão

- `pyfhirsdc/services/generateInteropMatrix.py.bak-v1` — versão anterior
  (apenas Observation/Condition, canonicalBase com bug).
- `MODIFICATIONS.md.bak-v1`, `HOWTO-matriz-interoperabilidade.md.bak-v1` —
  versões anteriores destes dois documentos.

## Versão 3 (v3) — detecção de coluna bilíngue PT-BR/EN

Motivação: o template oficial WHO SMART Guidelines L2 é publicado em inglês
(smart.who.int/ig-starter-kit); a maioria dos DAKs já publicados (Family
Planning, ANC, Imunização, TB, HIV) usa o template em inglês, e o projeto
deste trabalho é oficialmente em inglês. A v1/v2 comparavam cada coluna da
planilha com uma **string literal fixa em português** (ex.:
`"ID do elemento de dado*"`) — funciona só para essa tradução PT-BR
específica; qualquer outra redação (inclusive o template original em
inglês) simplesmente não seria reconhecida, sem erro nem aviso.

**Mudança:** `_classify_columns()` (nova) classifica cada coluna de uma aba
por **papel semântico**, comparando o cabeçalho normalizado (sem acento,
minúsculas, sem pontuação) contra listas de palavras-chave em PT-BR e em
inglês por papel (`id do elemento de dado` / `data element id`,
`descrição e definição` / `description and definition`, etc.), e por
sistema de terminologia (`icd-11`/`cid-11`, `snomed`, `loinc`, ...). A
comparação usa borda de palavra (`\b`), não substring solta.

**Limitação registrada e não resolvida por falta de acesso:** não foi
possível baixar o arquivo binário oficial do template em inglês a partir do
ambiente usado nesta modificação (rede bloqueou `smart.who.int` tanto via
linha de comando quanto via download direto pelo navegador embutido — só a
página HTML era acessível, não o `.xlsx`). Os aliases em inglês foram
construídos a partir da estrutura documentada publicamente pela OMS e de
convenções observadas (não são uma transcrição literal verificada do
arquivo oficial). **Antes de considerar o suporte a inglês "confirmado",
baixe o template real de
`https://smart.who.int/ig-starter-kit/DAK_core%20data%20dictionary_template_v2.xlsx`
e rode o script contra ele** — se o log mostrar "0 aba(s) de processo de
negócio detectada(s)" para um arquivo com dados, algum alias em
`COLUMN_ROLE_KEYWORDS`/`TERMINOLOGY_SYSTEM_DEFS` precisa de ajuste (é uma
mudança de uma linha, não uma reescrita).

**Bug real encontrado e corrigido durante o desenvolvimento desta versão:**
a palavra-chave de papel "título" `"nome"` batia, por substring solta, dentro
da própria palavra `"sNOMEd"` — fazendo a coluna de código SNOMED CT ser
classificada como coluna de título. Corrigido trocando substring solta por
correspondência de palavra/frase inteira (`\b...\b`); reforça por que a
mudança de substring para borda de palavra foi necessária, não só
teórica.

**Testes realizados:**
- Regressão completa contra o Mini-DAK HTA real (PT-BR): resultado
  idêntico à v2 — 26 elementos, 11/26 com terminologia, 7/7 tipos de
  recurso com exemplo gerado.
- Teste com planilha sintética em inglês (4 elementos, cabeçalhos como
  `"Data element ID*"`, `"ICD-11 code*"`, `"SNOMED CT preferred term"`
  etc., simulando um DAK de Family Planning): 1 aba detectada, 4/4
  elementos lidos, 2/4 com terminologia corretamente extraída (incluindo
  código, título/display e relacionamento), `CodeSystem` e `ConceptMap`
  gerados com o `canonicalBase` do teste, exemplos `Condition` e `Patient`
  gerados e validados.
- Não foi possível testar contra um DAK oficial real em inglês (ex.:
  Family Planning, ANC) por falta de acesso de rede ao arquivo original
  neste ambiente — recomendação registrada acima.

### Backups desta revisão

- `pyfhirsdc/services/generateInteropMatrix.py.bak-v2` — versão anterior
  (detecção de coluna por string literal fixa em PT-BR).

## Escopo do que esta modificação NÃO faz

- Não gera `Questionnaire`, `PlanDefinition`/CQL ou `StructureMap` a partir da
  lógica de decisão em DMN do Mini-DAK — isso exigiria o tradutor
  DMN → árvore de PlanDefinitionAction mencionado acima, não implementado.
- Não valida clinicamente o conteúdo do Mini-DAK — apenas estrutura os
  mapeamentos de terminologia já inseridos manualmente no dicionário de dados.
- Não decide, por conta própria, códigos de terminologia para elementos ainda
  não mapeados no dicionário de dados (ex.: estágio de HA / classificação da
  PA do ciclo) — isso é tratado separadamente, como pesquisa terminológica
  documentada e candidatos a confirmar, não como geração automática de
  código (ver relatório de pesquisa terminológica desta etapa).
- Não resolve, de forma definitiva, a lacuna de modelagem de "adesão
  medicamentosa" em FHIR discutida acima (v2.3) — apenas a documenta de
  forma explícita e rastreável no próprio exemplo gerado.
- Não modifica nem gera nenhum arquivo dentro da pasta `DAK/` do repositório
  do mestrado além dos artefatos de saída explicitamente gerados em
  `<outputPath>/interoperability-matrix/`.
- (v3) Não foi validada contra o arquivo binário oficial do template WHO em
  inglês nem contra um DAK oficial publicado (Family Planning, ANC, etc.) —
  só contra uma planilha sintética construída para o teste. Os aliases em
  inglês devem ser tratados como "melhor esforço documentado", não como
  cobertura garantida, até essa validação ser feita.
