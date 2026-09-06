# -*- coding: utf-8 -*-
"""
pyfhirsdc/services/generateInteropMatrix.py

Extensão adicionada ao pyfhirsdc para gerar, a partir do "core data dictionary"
de um DAK (template oficial WHO SMART Guidelines L2, Excel), uma matriz de
interoperabilidade consolidada e recursos FHIR de nível L3 (CodeSystem +
ConceptMap + exemplos de instância), sem depender do schema próprio
(pd./q./valueSet) usado pelo pipeline principal do pyfhirsdc (-o).

Este módulo NÃO contém, em hipótese alguma, dados de nenhum Mini-DAK
específico: ele lê arquivos externos, referenciados por caminho absoluto no
arquivo de configuração (chave já existente "data_dictionary_file"), da
mesma forma que process_data_dictionary_file() já faz em processInputFile.py.

--- Histórico de versões (ver MODIFICATIONS.md para o detalhamento) ---
v1: matriz consolidada (xlsx + md) + ConceptMap + 2 exemplos.
v2: fix canonicalBase; CodeSystem local; exemplos para os 7 tipos de recurso
    sugeridos.
v3: DETECÇÃO DE COLUNA POR PAPEL SEMÂNTICO (bilíngue PT-BR/EN), em vez de
    comparação com nome de coluna literal fixo. Motivação: o template oficial
    WHO SMART Guidelines L2 é publicado em inglês (smart.who.int/ig-starter-kit)
    e é a partir dele que localizações como a usada neste Mini-DAK (PT-BR) são
    traduzidas; outros Mini-DAKs (ex.: Family Planning, ANC, Imunização, TB)
    podem chegar tanto no template original em inglês quanto em outras
    traduções. Comparar com uma string fixa (ex.: "ID do elemento de dado*")
    funciona só para uma planilha idêntica a essa, byte a byte no cabeçalho —
    qualquer variação de wording (inclusive tradução) quebra silenciosamente
    a detecção. A v3 substitui isso por um classificador de colunas por
    palavras-chave normalizadas (sem acento, sem maiúsculas/pontuação), com
    listas de alias em PT-BR e em inglês por "papel" de coluna (ID do
    elemento, nome, descrição, tipo de dado, código/título/relação por
    sistema de terminologia). Isso é estritamente mais permissivo que a v2 —
    qualquer planilha que já funcionava continua funcionando (testado por
    regressão contra o Mini-DAK HTA real) — e passa a también reconhecer
    cabeçalhos em inglês, com uma lista de alias documentada e extensível
    (bastando adicionar uma palavra-chave, não reescrever código, quando uma
    variação de wording não reconhecida aparecer em um DAK futuro).

    IMPORTANTE — limitação registrada: não foi possível obter o arquivo
    binário oficial do template em inglês (smart.who.int/ig-starter-kit) a
    partir do ambiente de desenvolvimento usado nesta modificação (a rede
    disponível bloqueou o download do .xlsx); os aliases em inglês abaixo
    foram construídos a partir da estrutura documentada publicamente pela OMS
    (nomes dos componentes do DAK, terminologia usada na literatura sobre
    SMART Guidelines) e de convenções usuais de nomenclatura de coluna do
    próprio template original (cabeçalhos de aba como "COVER", "READ ME",
    "References", "DO NOT CHANGE List of Values" já aparecem em inglês mesmo
    na planilha PT-BR deste Mini-DAK, confirmando que o esqueleto do template
    é em inglês) — não são uma transcrição literal verificada do arquivo
    oficial. Antes de rodar contra um DAK oficial em inglês pela primeira
    vez, recomenda-se conferir o log ("N aba(s) de processo de negócio
    detectada(s)"): se vier com 0 abas para um arquivo que claramente tem
    dados, é sinal de que algum alias precisa ser ajustado — ver seção
    "Como adicionar um alias" no MODIFICATIONS.md.
"""

import json
import logging
import re
import unicodedata
from pathlib import Path

import pandas as pd

from pyfhirsdc.config import get_fhir_cfg, get_processor_cfg, read_config_file
from pyfhirsdc.serializers.inputFile import read_input_file

logger = logging.getLogger("default")

# --------------------------------------------------------------------------
# [v3] Normalização e classificação de colunas por papel semântico
# --------------------------------------------------------------------------

def _normalize(s):
    """minúsculas, sem acento, sem pontuação — só letras/números/espaço."""
    if s is None:
        return ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


def _matches_any(norm_text, keywords):
    """Casa cada palavra-chave como PALAVRA/FRASE INTEIRA (borda de palavra
    nos dois extremos), nunca como substring solta. Sem isso, uma
    palavra-chave curta como "nome" (papel de título) bate por acidente
    dentro de "sNOMEd" — bug real encontrado e corrigido durante os testes
    desta versão (ver MODIFICATIONS.md, v3)."""
    for kw in keywords:
        if re.search(r"\b" + re.escape(kw) + r"\b", norm_text):
            return True
    return False


# Papéis de coluna que não são específicos de um sistema de terminologia.
# Cada lista de palavras-chave já está normalizada (sem acento/pontuação).
COLUMN_ROLE_KEYWORDS = {
    "activity_id": ["id e nome da atividade", "id da atividade", "activity id",
                    "business process id"],
    "element_id": ["id do elemento de dado", "id elemento de dado",
                   "data element id", "dataelement id"],
    "element_name": ["nome do elemento de dado", "data element name",
                      "data element label"],
    "description": ["descricao e definicao", "description and definition",
                     "description definition"],
    "data_type": ["tipo de dado", "data type"],
    "obligatoriness": ["obrigatoriedade", "optionality", "requirement level",
                        "mandatory optional", "is required"],
}

# Sistema de terminologia -> aliases (já normalizados) usados para reconhecer
# QUALQUER coluna relacionada a ele, e a URI canônica FHIR do sistema.
TERMINOLOGY_SYSTEM_DEFS = {
    "CID-11": {"aliases": ["icd 11", "cid 11"],
               "uri": "http://id.who.int/icd/release/11/mms"},
    "CID-10": {"aliases": ["icd 10", "cid 10"],
               "uri": "http://hl7.org/fhir/sid/icd-10"},
    "LOINC": {"aliases": ["loinc"], "uri": "http://loinc.org"},
    "ICHI": {"aliases": ["ichi"], "uri": "http://id.who.int/ichi"},
    "CIF/ICF": {"aliases": ["icf", "cif"], "uri": "http://hl7.org/fhir/sid/icf"},
    "ATC": {"aliases": ["atc"], "uri": "http://www.whocc.no/atc"},
    "SNOMED CT": {"aliases": ["snomed"], "uri": "http://snomed.info/sct"},
}

# Dentro de uma coluna já identificada como pertencente a um sistema (por
# conter um dos aliases acima), estas palavras-chave decidem QUAL papel ela
# tem. A ordem importa: "relação"/"relationship" e as palavras de título são
# checadas ANTES de "código"/"code", porque no template PT-BR a própria
# coluna de título contém a palavra "código" dentro da frase ("Título do
# código CID-11") — checar código primeiro classificaria errado.
_REL_KEYWORDS = ["relacao", "relationship"]
_TITLE_KEYWORDS = ["titulo", "title", "nome", "display", "term", "label"]
_CODE_KEYWORDS = ["codigo", "code", "categoria"]

# Valores de célula que significam "não mapeado nesta terminologia" — tanto
# no template original em português quanto em uma eventual versão em inglês.
NAO_CLASSIFICAVEL = "Não classificável neste sistema"
_NOT_CLASSIFIABLE_NORMALIZED = {
    "nao classificavel neste sistema",
    "not classifiable in this system",
    "not applicable",
    "n a",
    "na",
}

FHIR_HINTS = [
    (r"press[aã]o arterial|\bpas\b|\bpad\b|blood pressure|\bsbp\b|\bdbp\b",
     "Observation", "Observation.value[x] (Quantity, mmHg) + Observation.code (LOINC)"),
    (r"diagn[oó]stico|est[aá]gio|\bdiagnos(is|ed)\b|\bstage\b",
     "Condition", "Condition.code (CID-10/CID-11/SNOMED CT) + Condition.clinicalStatus"),
    (r"identifica[cç][aã]o [uú]nica do paciente|\bcns\b|patient (unique )?id(entifier)?|\bmrn\b|national id",
     "Patient", "Patient.identifier"),
    (r"nome completo|full name|patient name",
     "Patient", "Patient.name"),
    (r"data de nascimento|date of birth|\bdob\b|birth ?date",
     "Patient", "Patient.birthDate"),
    (r"cefaleia|dor tor[aá]cica|dispneia|altera[cç][oõ]es visuais|altera[cç][oõ]es neurol[oó]gicas|sintoma|"
     r"headache|chest pain|dyspnea|shortness of breath|visual (disturbance|change)|neurolog\w* (change|symptom)|\bsymptom",
     "Observation", "Observation.value[x] (CodeableConcept) — sinal/sintoma"),
    (r"ades[aã]o|adherence|compliance",
     "MedicationStatement", "MedicationStatement.status (taken/not-taken)"),
    (r"classifica[cç][aã]o|classification",
     "Observation", "Observation.interpretation / Observation derivada"),
    (r"sinaliza[cç][aã]o de prioridade|alarme|priority (signal|flag)|\balert\b|\bflag\b",
     "Flag", "Flag.code / Flag.status"),
    (r"orienta[cç][aã]o|encaminhamento|contato|guidance|counsel(l)?ing|referral|\bcontact\b",
     "CommunicationRequest", "CommunicationRequest.payload / status"),
    (r"data do pr[oó]ximo ciclo|periodicidade|next (cycle|visit|appointment) date|periodicity|frequency of measurement",
     "Appointment", "Appointment.start / Appointment.minutesDuration"),
    (r"profissional respons[aá]vel|responsible (provider|professional|clinician)|assigned (provider|clinician)",
     "Practitioner", "Provenance.agent / PractitionerRole"),
]


def suggest_fhir(nome, descricao, tipo):
    texto = f"{nome or ''} {descricao or ''}".lower()
    for pattern, resource, path in FHIR_HINTS:
        if re.search(pattern, texto):
            return resource, path
    tipo_l = _normalize(tipo)
    if "booleano" in tipo_l or "boolean" in tipo_l:
        return "Observation", "Observation.value[x] (boolean)"
    if "data" in tipo_l or "hora" in tipo_l or "date" in tipo_l or "time" in tipo_l:
        return "Observation", "Observation.effectiveDateTime"
    if "lista" in tipo_l or "list" in tipo_l or "choice" in tipo_l:
        return "Observation", "Observation.value[x] (CodeableConcept)"
    if "quantidade" in tipo_l or "quantity" in tipo_l or "numer" in tipo_l:
        return "Observation", "Observation.value[x] (Quantity)"
    if tipo_l == "id":
        return "Identifier", "-"
    return "QuestionnaireResponse.item", "sem mapeamento clínico direto — capturado só no formulário"


def clean(v):
    if pd.isna(v):
        return None
    v = str(v).strip()
    if v == "" or _normalize(v) in _NOT_CLASSIFIABLE_NORMALIZED:
        return None
    return v


def _slug(elem_id):
    return elem_id.lower().replace(".", "-")


def _find_col(norm_to_raw, keywords):
    """Primeira coluna (nome original) cujo cabeçalho normalizado contém
    alguma das palavras-chave. norm_to_raw: lista de (normalizado, original)."""
    for norm, raw in norm_to_raw:
        if _matches_any(norm, keywords):
            return raw
    return None


def _classify_columns(columns):
    """[v3] Recebe a lista de nomes de coluna (como vieram do Excel) de uma
    aba e devolve:
      - roles: dict papel -> nome de coluna original (ou None)
      - terminology_cols: dict sistema -> {"code":.., "title":.., "rel":..}
    """
    norm_to_raw = [(_normalize(c), c) for c in columns]

    roles = {role: _find_col(norm_to_raw, kws) for role, kws in COLUMN_ROLE_KEYWORDS.items()}

    terminology_cols = {}
    for system, sysdef in TERMINOLOGY_SYSTEM_DEFS.items():
        cols_for_system = [(norm, raw) for norm, raw in norm_to_raw
                            if _matches_any(norm, sysdef["aliases"])]
        entry = {"code": None, "title": None, "rel": None}
        for norm, raw in cols_for_system:
            if _matches_any(norm, _REL_KEYWORDS):
                entry["rel"] = entry["rel"] or raw
            elif _matches_any(norm, _TITLE_KEYWORDS):
                entry["title"] = entry["title"] or raw
            elif _matches_any(norm, _CODE_KEYWORDS):
                entry["code"] = entry["code"] or raw
        if entry["code"] or entry["title"] or entry["rel"]:
            terminology_cols[system] = entry
    return roles, terminology_cols


def detect_business_process_sheets(xlsx_path, excluded_worksheets=None):
    """Detecta dinamicamente as abas de processo de negócio pela presença de
    uma coluna reconhecível como "ID do elemento de dado" (PT-BR ou EN),
    em vez de nomes de aba fixos ou uma string de coluna literal fixa."""
    excluded_worksheets = excluded_worksheets or []
    xl = pd.ExcelFile(xlsx_path)
    detected = []
    for sheet in xl.sheet_names:
        if sheet.lower() in [s.lower() for s in excluded_worksheets]:
            continue
        try:
            df_probe = pd.read_excel(xlsx_path, sheet_name=sheet, header=1, nrows=0)
        except Exception:
            continue
        roles, _ = _classify_columns(list(df_probe.columns))
        if roles.get("element_id"):
            detected.append(sheet)
    return detected


def load_dictionary(xlsx_path, excluded_worksheets=None):
    sheets = detect_business_process_sheets(xlsx_path, excluded_worksheets)
    logger.info("interop-matrix: %d aba(s) de processo de negócio detectada(s): %s", len(sheets), sheets)
    records = []
    for sheet in sheets:
        df = pd.read_excel(xlsx_path, sheet_name=sheet, header=1)
        roles, terminology_cols = _classify_columns(list(df.columns))
        id_col = roles["element_id"]
        for _, row in df.iterrows():
            elem_id = clean(row.get(id_col))
            if not elem_id:
                continue
            rec = {
                "Aba/processo": sheet,
                "ID atividade": clean(row.get(roles["activity_id"])) if roles["activity_id"] else None,
                "ID elemento": elem_id,
                "Nome do elemento": clean(row.get(roles["element_name"])) if roles["element_name"] else None,
                "Descrição": clean(row.get(roles["description"])) if roles["description"] else None,
                "Tipo de dado": clean(row.get(roles["data_type"])) if roles["data_type"] else None,
                "Obrigatoriedade": clean(row.get(roles["obligatoriness"])) if roles["obligatoriness"] else None,
            }
            mappings = {}
            for system, cols in terminology_cols.items():
                code = clean(row.get(cols["code"])) if cols["code"] else None
                title = clean(row.get(cols["title"])) if cols["title"] else None
                rel = clean(row.get(cols["rel"])) if cols["rel"] else None
                if code:
                    mappings[system] = {"code": code, "title": title, "relationship": rel,
                                         "uri": TERMINOLOGY_SYSTEM_DEFS[system]["uri"]}
                    rec[f"{system} código"] = code
                    rec[f"{system} título"] = title
            rec["_mappings"] = mappings
            resource, path = suggest_fhir(rec["Nome do elemento"], rec["Descrição"], rec["Tipo de dado"])
            rec["Recurso FHIR sugerido"] = resource
            rec["Path/observação FHIR"] = path
            records.append(rec)
    return records


def write_matrix_xlsx(records, out_path):
    all_cols = ["Aba/processo", "ID atividade", "ID elemento", "Nome do elemento",
                "Descrição", "Tipo de dado", "Obrigatoriedade"]
    term_cols = []
    for system in TERMINOLOGY_SYSTEM_DEFS:
        term_cols += [f"{system} código", f"{system} título"]
    all_cols += term_cols + ["Recurso FHIR sugerido", "Path/observação FHIR"]

    df_all = pd.DataFrame(records)
    for c in all_cols:
        if c not in df_all.columns:
            df_all[c] = None
    df_all = df_all[all_cols]

    has_term = df_all[[c for c in term_cols if c.endswith("código")]].notna().any(axis=1)
    df_term = df_all[has_term].reset_index(drop=True)

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df_term.to_excel(writer, sheet_name="Matriz consolidada", index=False)
        df_all.to_excel(writer, sheet_name="Todos os elementos", index=False)
    return df_term, df_all


def write_matrix_markdown(df_term, out_path):
    cols = ["Aba/processo", "ID elemento", "Nome do elemento"]
    for system in TERMINOLOGY_SYSTEM_DEFS:
        cols.append(f"{system} código")
    cols += ["Recurso FHIR sugerido"]
    df = df_term[cols].fillna("-")
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def build_codesystem(records, canonical_base):
    from fhir.resources.R4B.codesystem import CodeSystem, CodeSystemConcept
    concepts = [
        CodeSystemConcept(code=rec["ID elemento"], display=rec["Nome do elemento"],
                           definition=rec["Descrição"])
        for rec in records
    ]
    return CodeSystem(
        id="dak-data-elements",
        url=f"{canonical_base}CodeSystem/dak-data-elements",
        name="DAKDataElements",
        title="Elementos de dado do core data dictionary do DAK",
        status="draft",
        experimental=True,
        content="complete",
        description=(
            "CodeSystem local gerado automaticamente pelo módulo "
            "pyfhirsdc/services/generateInteropMatrix.py a partir do core data "
            "dictionary do DAK (template WHO SMART Guidelines L2). Cada código "
            "corresponde ao ID de um elemento de dado do dicionário; "
            "referenciado como 'source' do ConceptMap gerado no mesmo processo."
        ),
        count=len(concepts),
        concept=concepts,
    )


def build_conceptmap(records, canonical_base):
    from fhir.resources.R4B.conceptmap import (ConceptMap, ConceptMapGroup,
                                                 ConceptMapGroupElement,
                                                 ConceptMapGroupElementTarget)
    groups_by_system = {}
    for rec in records:
        for system, mapping in rec["_mappings"].items():
            groups_by_system.setdefault(system, {"target_uri": mapping["uri"], "elements": []})
            equivalence = {
                "Equivalent": "equivalent",
                "Related to": "relatedto",
                "Source is narrower than target": "narrower",
                "Source is broader than target": "wider",
            }.get(mapping.get("relationship") or "", "relatedto")
            target = ConceptMapGroupElementTarget(
                code=mapping["code"], display=mapping.get("title"), equivalence=equivalence)
            element = ConceptMapGroupElement(
                code=rec["ID elemento"], display=rec["Nome do elemento"], target=[target])
            groups_by_system[system]["elements"].append(element)

    groups = [
        ConceptMapGroup(source=f"{canonical_base}CodeSystem/dak-data-elements",
                         target=data["target_uri"], element=data["elements"])
        for system, data in groups_by_system.items()
    ]
    return ConceptMap(
        id="dak-data-elements-to-terminologies",
        url=f"{canonical_base}ConceptMap/dak-data-elements-to-terminologies",
        name="DAKDataElementsToTerminologies",
        title="Mapeamento de elementos de dado do DAK para terminologias padrão",
        status="draft",
        experimental=True,
        description=(
            "Mapeamento gerado automaticamente pelo módulo "
            "pyfhirsdc/services/generateInteropMatrix.py a partir do core data "
            "dictionary do DAK (template WHO SMART Guidelines L2)."
        ),
        group=groups,
    )


def build_example_resources(records, canonical_base):
    from fhir.resources.R4B.observation import Observation
    from fhir.resources.R4B.condition import Condition
    from fhir.resources.R4B.patient import Patient
    from fhir.resources.R4B.appointment import Appointment, AppointmentParticipant
    from fhir.resources.R4B.medicationstatement import MedicationStatement
    from fhir.resources.R4B.flag import Flag
    from fhir.resources.R4B.communicationrequest import (CommunicationRequest,
                                                            CommunicationRequestPayload)
    from fhir.resources.R4B.codeableconcept import CodeableConcept
    from fhir.resources.R4B.coding import Coding
    from fhir.resources.R4B.quantity import Quantity
    from fhir.resources.R4B.reference import Reference
    from fhir.resources.R4B.humanname import HumanName
    from fhir.resources.R4B.identifier import Identifier
    from fhir.resources.R4B.annotation import Annotation

    by_type = {}
    for rec in records:
        by_type.setdefault(rec["Recurso FHIR sugerido"], []).append(rec)

    examples = {}
    patient_ref = Reference(reference="Patient/exemplo-paciente")

    def codings_from(rec, systems):
        out = []
        for sysname in systems:
            m = rec["_mappings"].get(sysname)
            if m:
                out.append(Coding(system=m["uri"], code=m["code"], display=m.get("title")))
        return out

    try:
        for rec in by_type.get("Observation", []):
            if "LOINC" in rec["_mappings"]:
                codings = codings_from(rec, ["LOINC", "SNOMED CT"])
                obs = Observation(
                    id=f"exemplo-{_slug(rec['ID elemento'])}",
                    status="final",
                    category=[CodeableConcept(coding=[Coding(
                        system="http://terminology.hl7.org/CodeSystem/observation-category",
                        code="vital-signs", display="Vital Signs")])],
                    code=CodeableConcept(coding=codings, text=rec["Nome do elemento"]),
                    subject=patient_ref,
                    effectiveDateTime="2026-09-04T08:00:00-03:00",
                    valueQuantity=Quantity(value=138, unit="mmHg",
                                            system="http://unitsofmeasure.org", code="mm[Hg]"),
                )
                examples[f"Observation-{rec['ID elemento']}"] = obs
                break
    except Exception as e:
        logger.warning("interop-matrix: falha ao gerar exemplo Observation: %s", e)

    try:
        for rec in by_type.get("Condition", []):
            if "CID-10" in rec["_mappings"]:
                codings = codings_from(rec, ["CID-10", "CID-11", "SNOMED CT"])
                cond = Condition(
                    id=f"exemplo-{_slug(rec['ID elemento'])}",
                    clinicalStatus=CodeableConcept(coding=[Coding(
                        system="http://terminology.hl7.org/CodeSystem/condition-clinical",
                        code="active", display="Active")]),
                    verificationStatus=CodeableConcept(coding=[Coding(
                        system="http://terminology.hl7.org/CodeSystem/condition-ver-status",
                        code="confirmed", display="Confirmed")]),
                    code=CodeableConcept(coding=codings, text=rec["Nome do elemento"]),
                    subject=patient_ref,
                )
                examples[f"Condition-{rec['ID elemento']}"] = cond
                break
    except Exception as e:
        logger.warning("interop-matrix: falha ao gerar exemplo Condition: %s", e)

    try:
        patient_recs = by_type.get("Patient", [])
        if patient_recs:
            ident_rec = next((r for r in patient_recs if re.search(r"identifi|cns", r["Nome do elemento"] or "", re.I)), None)
            name_rec = next((r for r in patient_recs if re.search(r"nome|name", r["Nome do elemento"] or "", re.I)), None)
            dob_rec = next((r for r in patient_recs if re.search(r"nascimento|birth", r["Nome do elemento"] or "", re.I)), None)
            kwargs = {"id": "exemplo-paciente"}
            if ident_rec:
                kwargs["identifier"] = [Identifier(
                    system=f"{canonical_base}NamingSystem/{_slug(ident_rec['ID elemento'])}",
                    value="EXEMPLO-000001")]
            if name_rec:
                kwargs["name"] = [HumanName(text="Paciente de Exemplo", family="Exemplo", given=["Paciente"])]
            if dob_rec:
                kwargs["birthDate"] = "1965-01-01"
            examples["Patient-exemplo-paciente"] = Patient(**kwargs)
    except Exception as e:
        logger.warning("interop-matrix: falha ao gerar exemplo Patient: %s", e)

    try:
        appt_recs = by_type.get("Appointment", [])
        if appt_recs:
            period_rec = next((r for r in appt_recs if re.search(r"periodicidade|periodicity|frequency", r["Nome do elemento"] or "", re.I)), None)
            date_rec = next((r for r in appt_recs if re.search(r"data|date", r["Nome do elemento"] or "", re.I)), None)
            kwargs = dict(
                id="exemplo-proximo-ciclo",
                status="booked",
                description="Próximo ciclo de telemonitoramento",
                participant=[AppointmentParticipant(actor=patient_ref, status="accepted")],
            )
            if date_rec:
                kwargs["start"] = "2026-09-11T08:00:00-03:00"
                kwargs["end"] = "2026-09-11T08:15:00-03:00"
            if period_rec:
                kwargs["comment"] = (
                    f"Periodicidade configurada pelo elemento {period_rec['ID elemento']} "
                    f"({period_rec['Nome do elemento']})."
                )
            examples["Appointment-exemplo-proximo-ciclo"] = Appointment(**kwargs)
    except Exception as e:
        logger.warning("interop-matrix: falha ao gerar exemplo Appointment: %s", e)

    try:
        for rec in by_type.get("MedicationStatement", []):
            codings = codings_from(rec, ["SNOMED CT", "CID-10"])
            note = None
            if codings:
                desc = "; ".join(f"{c.system} {c.code} ({c.display})" for c in codings)
                note = [Annotation(text=(
                    f"Elemento de dado '{rec['Nome do elemento']}' ({rec['ID elemento']}) mapeado no "
                    f"dicionário de dados para {desc}. Observação metodológica: FHIR não possui, dentro "
                    "de MedicationStatement, um elemento estruturado dedicado a 'grau de adesão'; os "
                    "códigos foram anotados aqui para rastreabilidade em vez de forçados em "
                    "medicationCodeableConcept."
                ))]
            med = MedicationStatement(
                id=f"exemplo-{_slug(rec['ID elemento'])}",
                status="unknown",
                medicationCodeableConcept=CodeableConcept(
                    text="Medicação (classe não especificada no elemento de dado)"),
                subject=patient_ref,
                note=note,
            )
            examples[f"MedicationStatement-{rec['ID elemento']}"] = med
            break
    except Exception as e:
        logger.warning("interop-matrix: falha ao gerar exemplo MedicationStatement: %s", e)

    try:
        for rec in by_type.get("Flag", []):
            flag = Flag(
                id=f"exemplo-{_slug(rec['ID elemento'])}",
                status="active",
                category=[CodeableConcept(coding=[Coding(
                    system="http://terminology.hl7.org/CodeSystem/flag-category",
                    code="clinical", display="Clinical")])],
                code=CodeableConcept(text=rec["Nome do elemento"]),
                subject=patient_ref,
            )
            examples[f"Flag-{rec['ID elemento']}"] = flag
            break
    except Exception as e:
        logger.warning("interop-matrix: falha ao gerar exemplo Flag: %s", e)

    try:
        for rec in by_type.get("CommunicationRequest", []):
            comm = CommunicationRequest(
                id=f"exemplo-{_slug(rec['ID elemento'])}",
                status="completed",
                payload=[CommunicationRequestPayload(contentString=rec["Nome do elemento"])],
                subject=patient_ref,
            )
            examples[f"CommunicationRequest-{rec['ID elemento']}"] = comm
            break
    except Exception as e:
        logger.warning("interop-matrix: falha ao gerar exemplo CommunicationRequest: %s", e)

    return examples


def process_interop_matrix(conf=None):
    """Ponto de entrada chamado pelo main.py com a flag -m/--matrix."""
    if conf is not None:
        read_config_file(conf)
    cfg = get_processor_cfg()
    if not hasattr(cfg, "data_dictionary_file") or not cfg.data_dictionary_file:
        logger.error("interop-matrix: 'data_dictionary_file' ausente na configuração")
        return
    dict_path = cfg.data_dictionary_file
    excluded = getattr(cfg, "data_dictionary_exclude_workSheets", [])

    fhir_cfg = get_fhir_cfg()
    canonical_base = getattr(fhir_cfg, "canonicalBase", None) or "http://example.org/fhir/"

    out_dir = Path(cfg.outputPath) / "interoperability-matrix"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("interop-matrix: lendo %s", dict_path)
    records = load_dictionary(dict_path, excluded)
    logger.info("interop-matrix: %d elementos de dado lidos", len(records))
    if len(records) == 0:
        logger.warning(
            "interop-matrix: nenhum elemento de dado foi reconhecido. Verifique se "
            "alguma aba tem uma coluna de 'ID do elemento de dado' (PT-BR ou EN) "
            "detectável — ver COLUMN_ROLE_KEYWORDS em generateInteropMatrix.py."
        )

    xlsx_out = out_dir / "matriz_interoperabilidade.xlsx"
    df_term, df_all = write_matrix_xlsx(records, xlsx_out)
    logger.info("interop-matrix: matriz consolidada (%d/%d elementos com terminologia) -> %s",
                len(df_term), len(df_all), xlsx_out)

    md_out = out_dir / "matriz_interoperabilidade.md"
    write_matrix_markdown(df_term, md_out)
    logger.info("interop-matrix: versão markdown -> %s", md_out)

    try:
        cs = build_codesystem(records, canonical_base)
        cs_out = out_dir / "CodeSystem-dak-data-elements.json"
        cs_out.write_text(cs.json(indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("interop-matrix: CodeSystem FHIR validado -> %s", cs_out)
    except Exception as e:
        logger.warning("interop-matrix: falha ao gerar CodeSystem: %s", e)

    try:
        cm = build_conceptmap(records, canonical_base)
        cm_out = out_dir / "ConceptMap-data-elements-to-terminologies.json"
        cm_out.write_text(cm.json(indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("interop-matrix: ConceptMap FHIR validado -> %s", cm_out)
    except Exception as e:
        logger.warning("interop-matrix: falha ao gerar ConceptMap: %s", e)

    try:
        examples = build_example_resources(records, canonical_base)
        ex_dir = out_dir / "examples"
        ex_dir.mkdir(exist_ok=True)
        for name, resource in examples.items():
            (ex_dir / f"{name}.json").write_text(resource.json(indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("interop-matrix: exemplo FHIR validado -> %s", ex_dir / f"{name}.json")
        logger.info("interop-matrix: %d/7 tipo(s) de recurso com exemplo gerado (%s)",
                    len(examples), ", ".join(sorted(n.split("-")[0] for n in examples)))
    except Exception as e:
        logger.warning("interop-matrix: falha ao gerar exemplos de instância: %s", e)
