"""Quick test script to verify the plugin's search logic works."""

import asyncio

from docs2db_api.rag.engine import UniversalRAGEngine, RAGConfig

QUESTIONS = [
    "how do I fork a repo on Pagure?",
    "git clone ssh failing on src.fedoraproject.org",
    "how do I become a Fedora contributor?",
]


async def test():
    engine = UniversalRAGEngine(
        config=RAGConfig(
            similarity_threshold=0.5,
            max_chunks=3,
            enable_question_refinement=False,
            enable_reranking=True,
        ),
    )
    await engine.start()

    for q in QUESTIONS:
        print(f"\n{'='*60}")
        print(f"Q: {q}")
        print('='*60)
        result = await engine.search_documents(q)
        docs = result.documents if hasattr(result, "documents") else []
        if not docs:
            print("No results found.")
            continue
        for i, doc in enumerate(docs[:3], 1):
            text = doc.get("text", "").strip()[:300]
            source = doc.get("source", "unknown")
            print(f"\n  {i}. {text}...")
            print(f"     source: {source}")

    await engine.close()
    print("\nDone.")


asyncio.run(test())
