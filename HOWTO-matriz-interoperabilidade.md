# Como executar: matriz de interoperabilidade + FHIR L3 (Mini-DAK HTA)

Guia de execução do que foi adicionado neste fork (ver `MODIFICATIONS.md` para
o detalhamento técnico das modificações, incluindo a revisão v2). Escreva
estes passos, ou um resumo deles, na seção de metodologia do relatório — cada
etapa abaixo já foi testada de ponta a ponta contra as planilhas reais do
Mini-DAK HTA.

## 0. Pré-requisitos

- Python 3.10+ instalado.
- Este fork clonado localmente (`cesaraugustomt/pyfhirsdc`).
- A pasta do Mini-DAK (`DAK/L2_oficial_FINAL/`, com o
  `HTA_L2_core_data_dictionary.xlsx` e o `HTA_L2_decision-support_logic.xlsx`)
  acessível no mesmo computador — **fora** da pasta do pyfhirsdc.

## 1. Instalar as dependências (com a versão de Pydantic compatível)

O `pyproject.toml` original não fixa uma versão máxima de `fhir.resources`,
o que hoje resolve para uma versão que exige Pydantic v2 — incompatível com
o código nativo do pyfhirsdc (ver `MODIFICATIONS.md`, seção "incompatibilidade
de dependências"). Por isso, instale nesta ordem exata:

```bash
cd pyfhirsdc   # a pasta deste fork

# 1a. dependências principais, com Pydantic fixado na série 1.x
pip install "pydantic<2" "fhir.resources==7.0.2"


# 1b. demais dependências do projeto
pip install wheel validators odfpy ocldev requests-toolbelt jsonpath-ng \
            textile fhirpathpy semantic-version py-markdown-table pandas openpyxl coloredlogs

# 1c. registrar o próprio pyfhirsdc como pacote instalado (necessário para
#     que pyfhirsdc/version.py consiga ler a própria versão), sem reinstalar
#     dependências (senão o passo 1a é desfeito):
pip install --no-deps -e .
```

Confira que ficou consistente:

```bash
python3 -c "import pydantic; print(pydantic.VERSION)"        # deve começar com 1.
python3 -c "import fhir.resources; print(fhir.resources.__version__)"  # 7.0.x
python3 -c "import importlib.metadata as m; print(m.version('pyfhirsdc'))"  # 0.1.3
```

## 2. Ajustar o arquivo de configuração

Este fork inclui um template genérico e rastreado no repositório,
`conf.matrix.example.json`. Copie-o para um novo arquivo antes de editar —
por exemplo `conf-<nome-do-seu-mini-dak>.json`. Arquivos com o padrão
`conf-*.json` já ficam automaticamente fora do git (regra existente no
`.gitignore`), então o caminho real dos arquivos no seu computador nunca
vai parar no repositório — nem o seu, nem o de outros grupos que também
usarem este fork. Ele **não contém nenhum dado do Mini-DAK** — só caminhos
de arquivo. Ajuste os quatro caminhos abaixo para onde o seu Mini-DAK
realmente está no seu computador:

```json
{
    "processor": {
        "inputFile": "/caminho/para/seu/DAK/L2/core_data_dictionary.xlsx",
        "data_dictionary_file": "/caminho/para/seu/DAK/L2/core_data_dictionary.xlsx",
        "decision_support_logic_file": "/caminho/para/seu/DAK/L2/decision-support_logic.xlsx",
        "outputPath": "/caminho/para/seu/DAK/L2",
        "build": 0,
        "environment": "dev"
    },
    "fhir": {
        "canonicalBase": "http://seu-mini-dak.example.org/fhir/",
        "lib_version": "0.1.0"
    }
}
```

`fhir.lib_version` é **obrigatório** mesmo para a flag `-m` — não é usado pela
matriz em si, mas `main.py` sempre chama `updateBuildNumber()` antes de
checar qualquer flag, e essa função lê `fhir.lib_version` diretamente, sem
valor padrão. Sem esse campo, a execução quebra com
`AttributeError: 'SimpleNamespace' object has no attribute 'lib_version'`
antes mesmo de chegar na geração da matriz — foi verificado de ponta a
ponta contra o template mínimo antes desta revisão do HOWTO.

Observações sobre `inputFile`: o pyfhirsdc exige, na leitura da configuração,
que esse caminho exista — mesmo quando você só vai usar a flag `-m` (que não
usa o schema `pd./q.` que `inputFile` normalmente alimenta). É uma exigência
não documentada do código original (`pyfhirsdc/config.py`, função
`read_config_file`). Por isso, aqui apontamos `inputFile` para o próprio
arquivo do dicionário de dados — ele só precisa existir, seu conteúdo não é
usado pela flag `-m`.

`outputPath` deve apontar para a pasta do Mini-DAK onde você quer que os
artefatos gerados apareçam — a ferramenta cria automaticamente uma subpasta
`interoperability-matrix/` dentro dela.

`fhir.canonicalBase` (a partir da revisão v2) agora é de fato usado para
compor as URLs do `CodeSystem` e do `ConceptMap` gerados — na v1 esse valor
era lido incorretamente e a ferramenta sempre caía em
`http://example.org/fhir/` (ver `MODIFICATIONS.md`, seção v2.1).

## 3. Executar

```bash
python3 main.py -c conf-<nome-do-seu-mini-dak>.json -m
```

Saída esperada no terminal (exemplo real de execução, revisão v2):

```
INFO Process interoperability matrix
INFO interop-matrix: lendo .../HTA_L2_core_data_dictionary.xlsx
INFO interop-matrix: 5 aba(s) de processo de negócio detectada(s): [...]
INFO interop-matrix: 26 elementos de dado lidos
INFO interop-matrix: matriz consolidada (9/26 elementos com terminologia) -> .../matriz_interoperabilidade.xlsx
INFO interop-matrix: versão markdown -> .../matriz_interoperabilidade.md
INFO interop-matrix: CodeSystem FHIR validado -> .../CodeSystem-dak-data-elements.json
INFO interop-matrix: ConceptMap FHIR validado -> .../ConceptMap-data-elements-to-terminologies.json
INFO interop-matrix: exemplo FHIR validado -> .../examples/Observation-HTA.B1.DE1.json
INFO interop-matrix: exemplo FHIR validado -> .../examples/Condition-HTA.A1.DE4.json
INFO interop-matrix: exemplo FHIR validado -> .../examples/Patient-exemplo-paciente.json
INFO interop-matrix: exemplo FHIR validado -> .../examples/Appointment-exemplo-proximo-ciclo.json
INFO interop-matrix: exemplo FHIR validado -> .../examples/MedicationStatement-HTA.B4.DE1.json
INFO interop-matrix: exemplo FHIR validado -> .../examples/Flag-HTA.C4.DE2.json
INFO interop-matrix: exemplo FHIR validado -> .../examples/CommunicationRequest-HTA.D2.DE1.json
INFO interop-matrix: 7/7 tipo(s) de recurso com exemplo gerado (Appointment, CommunicationRequest, Condition, Flag, MedicationStatement, Observation, Patient)
```

Nota: cada execução do `main.py` (com qualquer flag) atualiza automaticamente
o número de build dentro do próprio arquivo de configuração (`conf-*.json`)
que você criou a partir do template — comportamento herdado
do pyfhirsdc original (`updateBuildNumber`), não algo introduzido por esta
modificação. Isso acontece mesmo que a execução falhe depois (ex.: por um
caminho de arquivo incorreto) — se isso ocorrer, o número de build ainda
assim é incrementado; não é um sinal de erro na modificação em si.

## 4. Onde ficam os artefatos gerados

Dentro de `<outputPath>/interoperability-matrix/`:

| Arquivo | Conteúdo |
|---|---|
| `matriz_interoperabilidade.xlsx` | Aba "Matriz consolidada" (só elementos com código de terminologia) e aba "Todos os elementos" (auditoria completa) |
| `matriz_interoperabilidade.md` | A mesma matriz consolidada, em Markdown, pronta para colar no manuscrito |
| `CodeSystem-dak-data-elements.json` | Recurso FHIR `CodeSystem` (R4B) com um `concept` por elemento de dado do dicionário — desde a v2, fecha a referência `source` usada pelo `ConceptMap` |
| `ConceptMap-data-elements-to-terminologies.json` | Recurso FHIR `ConceptMap` (R4B), validado estruturalmente; desde a v2, `url` e `group[].source` usam o `canonicalBase` configurado |
| `examples/Patient-*.json` | Exemplo de instância `Patient` (identificador, nome, data de nascimento) |
| `examples/Condition-*.json` | Exemplo de instância `Condition` (ex.: diagnóstico de HA) |
| `examples/Appointment-*.json` | Exemplo de instância `Appointment` (próximo ciclo de medição) |
| `examples/Observation-*.json` | Exemplo de instância `Observation` (ex.: PAS) |
| `examples/MedicationStatement-*.json` | Exemplo de instância `MedicationStatement` (adesão medicamentosa — ver limitação de modelagem registrada em `MODIFICATIONS.md`, seção v2.3) |
| `examples/Flag-*.json` | Exemplo de instância `Flag` (sinalização de prioridade/alarme) |
| `examples/CommunicationRequest-*.json` | Exemplo de instância `CommunicationRequest` (orientação registrada) |

Antes da v2, apenas os dois primeiros exemplos (`Observation`, `Condition`)
eram gerados; os demais 5 tipos de recurso sugeridos pela matriz ficavam sem
nenhum exemplo de instância correspondente.

## 5. Suporte a templates em inglês (v3)

Desde a v3, a detecção de colunas não depende mais de nomes de coluna fixos
em português — o script classifica cada coluna por palavra-chave (PT-BR e
EN) e por borda de palavra, não por string literal exata. Isso significa
que, além do template PT-BR usado neste Mini-DAK, o script deve reconhecer
também o template oficial WHO SMART Guidelines L2 em inglês.

**Isso ainda não foi verificado contra o arquivo oficial real** — o
ambiente usado para desenvolver esta modificação não conseguiu baixar o
`.xlsx` de
`https://smart.who.int/ig-starter-kit/DAK_core%20data%20dictionary_template_v2.xlsx`
(rede bloqueada). Foi testado apenas contra uma planilha sintética
construída para imitar a estrutura esperada. Antes de usar o script contra
um DAK oficial em inglês pela primeira vez (ex.: Family Planning, ANC),
baixe o template real e rode `python3 main.py -c <conf> -m` contra ele —
se o log mostrar `0 aba(s) de processo de negócio detectada(s)` para um
arquivo que claramente tem dados, um alias em `COLUMN_ROLE_KEYWORDS` ou
`TERMINOLOGY_SYSTEM_DEFS` (em `generateInteropMatrix.py`) precisa de um
ajuste — é uma lista de palavras-chave, não uma reescrita de código.

## 6. Re-executar após atualizar o Mini-DAK

Basta rodar o comando do passo 3 de novo — os arquivos são sobrescritos.
Não é necessário repetir os passos 1 e 2, a menos que o ambiente Python seja
recriado.
