import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'services' / 'api'))

from app.db.base import Base, reset_engine
from app.llm.provider import get_llm_provider, GeminiProvider
from app.evaluation.runner import run_full_benchmark

async def main():
    # 1. Initialize SQLite benchmark database
    db_path = Path('data/benchmark/benchmark.db')
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = await reset_engine(f'sqlite+aiosqlite:///{db_path.resolve().as_posix()}')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. Resolve LLM Provider
    provider = get_llm_provider()
    print(f'Executing Benchmark with provider: {type(provider).__name__}')
    if not isinstance(provider, GeminiProvider):
        raise RuntimeError(f'Expected GeminiProvider, got {type(provider).__name__}')

    # 3. Run Benchmark Suite (14 incidents)
    report = await run_full_benchmark(llm_provider=provider, use_cache=True)
    print('\n' + '='*80)
    print('BENCHMARK COMPLETED')
    print('='*80)
    print(f'TRACE Accuracy: {report.trace_accuracy*100:.1f}% vs Baseline: {report.baseline_accuracy*100:.1f}%')
    print(f'TRACE Top-3 Accuracy: {report.trace_top_3_accuracy*100:.1f}%')
    print(f'Evidence Precision: {report.trace_average_evidence_precision*100:.1f}%')
    print(f'TRACE Avg Confidence: {report.trace_average_confidence:.1f}%')
    print(f'Baseline Avg Confidence: {report.baseline_average_confidence:.1f}%')
    print(f'Hallucination Rate: {report.trace_hallucination_rate*100:.2f}%')

if __name__ == '__main__':
    asyncio.run(main())
