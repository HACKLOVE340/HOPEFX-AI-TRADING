# 0015. Adopt embedding-based news sentiment

- Status: accepted
- Date: 2026-09-09

## Context

Decision #17. News sentiment is scored by `news/sentiment.py` using TextBlob —
a keyword and polarity-lexicon approach. Group 3 Chapter 16 wants semantic
search with provenance, and Group 1 wants retrieval-augmented context for the
agent. Both want embeddings.

`faiss` is not installed. `research/vector_store.py` already uses ChromaDB
embeddings for market-regime retrieval, so the platform is not starting from
nothing — but news sentiment does not use it.

## Options considered

- **Adopt it.** Costs: a new dependency chain in a money-moving image. The
  common path is `sentence-transformers`, which pulls `torch` — and
  `requirements.txt` already pins around torch specifically "to avoid accidental
  GPU builds on CPU nodes". Image size and cold-start both grow.
- **Decline for now.** Costs: sentiment stays lexicon-based, and Group 3's
  semantic search stays blocked. Zero risk, zero image growth.
- **Prototype outside the image first**, measure against the keyword scorer,
  then decide. Costs: slower, and it defers a decision the owner is willing to
  make now.

## Decision

Adopt it. The owner chose this on 2026-09-09, having been shown the dependency
cost and the recommendation against.

**The recommendation was to decline, and it was overruled deliberately.** That
is recorded here rather than softened, because the next person to meet this
dependency chain deserves to know it was a considered trade and not an
oversight.

Two constraints follow from the objection rather than from the feature, and
they are part of this decision:

1. **`faiss-cpu`, never `faiss-gpu`.** The index does not need a GPU and the
   image must not acquire a CUDA dependency by accident.
2. **The embedding model must not drag in `torch` unless measured to be
   necessary.** `sentence-transformers` is the convenient path, not the only
   one; an ONNX or hashing-based embedder is evaluated first, and if `torch`
   is adopted anyway that is a second decision with its own record.

## Consequences

Makes semantic recall available to news sentiment and unblocks Group 3 item 13
(semantic search with provenance).

Makes the production image larger and its dependency surface wider, in a
codebase whose own rules treat the image as part of the money path. The two
constraints above are what keep that growth bounded, and dropping either one
reverses this decision in substance.

Makes a comparison obligatory rather than optional: if the embedding scorer does
not beat the keyword scorer on a measured set, the right outcome is to keep the
dependency out and supersede this record. Adopting a heavier path that scores no
better is the failure mode to watch for.

## Evidence

    python -c "import faiss"   ->  ModuleNotFoundError
    requirements.txt:105       ->  "sentence-transformers pulls torch; pin to
                                    avoid accidental GPU builds on CPU nodes"

`research/vector_store.py` shows the platform already runs an embedding store
(ChromaDB, embedded), so the retrieval pattern is established here.
