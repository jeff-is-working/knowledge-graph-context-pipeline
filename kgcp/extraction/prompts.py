"""LLM prompts for SPO extraction, entity resolution, and inference.

These are adapted from AIKG's proven prompt templates.
"""

# -- Phase 1: SPO Extraction --------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """\
You are an advanced AI system specialized in knowledge extraction and \
knowledge graph generation. Your expertise includes identifying consistent \
entity references and meaningful relationships in text.
CRITICAL INSTRUCTION: All relationships (predicates) MUST be no more than \
3 words maximum. Ideally 1-2 words. This is a hard limit."""

EXTRACTION_USER_PROMPT = """\
From the text below, extract all knowledge as Subject-Predicate-Object triples.

Rules:
1. Entity Consistency: Use the same name for the same entity throughout \
(e.g., always "john smith", not "john" or "mr. smith").
2. Atomic Terms: Identify distinct entities — people, organizations, \
locations, concepts, tools, techniques.
3. Replace Pronouns: Replace he/she/it/they with actual entity names.
4. Pairwise Relationships: One triple per meaningful relationship.
5. Predicate Length: 1-3 words MAXIMUM (hard limit).
6. Completeness: Capture ALL meaningful relationships.
7. Lowercase: All text must be lowercase.

Return ONLY a JSON array:
[
  {"subject": "entity a", "predicate": "targets", "object": "entity b"},
  {"subject": "entity c", "predicate": "uses", "object": "entity d"}
]

Text:
```
{text}
```
"""

# -- Phase 2: Entity Resolution -----------------------------------------------

ENTITY_RESOLUTION_SYSTEM_PROMPT = """\
You are an expert in entity resolution and knowledge graph normalization. \
Your task is to identify entities that refer to the same real-world thing \
and provide a single standardized name for each group."""

ENTITY_RESOLUTION_USER_PROMPT = """\
Given these entities from a knowledge graph, group any that refer to the \
same real-world entity. Return a JSON object mapping the standardized name \
to a list of variants.

Only group entities you are confident refer to the same thing. If an entity \
has no variants, omit it.

Entities:
{entities}

Return ONLY JSON:
{{"standardized name": ["variant1", "variant2"]}}
"""

# -- Phase 3: Relationship Inference -------------------------------------------

INFERENCE_SYSTEM_PROMPT = """\
You are an expert in knowledge graph analysis. Given entities from different \
communities in a knowledge graph, infer plausible relationships between them."""

INFERENCE_USER_PROMPT = """\
These entities come from different communities in a knowledge graph about \
the topic described below. Infer 2-3 plausible relationships between \
entities from different communities.

Communities:
{communities}

Return ONLY a JSON array of triples:
[{{"subject": "entity a", "predicate": "relates to", "object": "entity b"}}]
"""
