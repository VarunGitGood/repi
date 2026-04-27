import asyncio
import os
import json
from src.app.core.container import Container
from src.app.investigation.react_loop import InvestigationStep

async def main():
    container = Container()
    await container.init_db()
    await container.init_known_services()
    
    query = "Why did auth-service fail around 00:44 on April 28?"
    
    print(f"Starting investigation for: {query}\n")
    
    async def on_step(step: InvestigationStep):
        print(f"--- Step {step.step_number} ---")
        print(f"Thought: {step.thought.content}")
        if step.action:
            print(f"Action: {step.action.tool_call.name}({step.action.tool_call.args})")
        if step.observation:
            res = step.observation.tool_result.result
            if res:
                print(f"Observation: Found {len(res) if isinstance(res, list) else 'results'}")
            else:
                print(f"Observation: {step.observation.tool_result.error or 'No results'}")
        print("\n")

    async with container.async_session_maker() as session:
        loop = container.get_investigation_loop(session)
        result = await loop.investigate(query, on_step=on_step)
        
        print("=== FINAL ANSWER ===")
        print(result.answer)
        print(f"\nConfidence: {result.confidence}")
        print(f"Duration: {result.duration_seconds:.2f}s")
        print(f"Evidence Chunks: {len(result.evidence_chunk_ids)}")

if __name__ == "__main__":
    asyncio.run(main())
