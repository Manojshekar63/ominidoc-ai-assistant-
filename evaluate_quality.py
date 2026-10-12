import os
import sys
import types
from typing import List, Dict
from unittest.mock import MagicMock
import json
import time

# --- 1. SETUP & MOCKING (Same as performance test to ensure app2 loads) ---
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

# Robust Streamlit mock
streamlit_mod = types.ModuleType("streamlit")
components_mod = types.ModuleType("streamlit.components")
components_v1 = types.ModuleType("streamlit.components.v1")
components_v1.declare_component = lambda *a, **k: MagicMock()
components_v1.html = lambda *a, **k: None
components_mod.v1 = components_v1
streamlit_mod.components = components_mod
streamlit_mod.session_state = {}
streamlit_mod.write = lambda *a, **k: None
streamlit_mod.empty = lambda *a, **k: MagicMock()
streamlit_mod.sidebar = types.SimpleNamespace()
sys.modules["streamlit"] = streamlit_mod
sys.modules["streamlit.components"] = components_mod
sys.modules["streamlit.components.v1"] = components_v1

# Robust import of app2
try:
    import importlib
    app2 = importlib.import_module("app2")
except Exception:
    import importlib.util
    app2_path = os.path.join(script_dir, "app2.py")
    if not os.path.exists(app2_path):
        print("Error: Could not find app2.py")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("app2", app2_path)
    app2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app2)

app2.st = sys.modules["streamlit"]

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import ChatOllama

# --- 2. EVALUATION LOGIC ---

class QualityEvaluator:
    def __init__(self, model_name="llama3.2:3b"):
        self.model_name = model_name
        self.llm = ChatOllama(model=model_name, base_url=app2.OLLAMA_HOST)
        self.console_width = 70

    def get_eval_dataset(self):
        """Returns a small Gold Standard dataset for testing."""
        # Source Text mimicking a technical manual or report
        source_text = (
            "OmniDoc AI is a local RAG application designed for privacy-conscious users. "
            "It supports PDF, DOCX, and URL ingestion. "
            "The system uses FAISS for vector storage and runs on standard consumer hardware like i3 laptops. "
            "Unlike cloud solutions, OmniDoc keeps all data on the local machine, preventing data leaks. "
            "The default embedding model is from Hugging Face, specifically optimized for CPU usage."
        )
        
        # Ground Truth Q&A (Question, Correct Answer)
        qa_pairs = [
            {
                "question": "What storage system does OmniDoc AI use?",
                "ground_truth": "It uses FAISS for vector storage."
            },
            {
                "question": "Why is OmniDoc AI different from cloud solutions?",
                "ground_truth": "It keeps all data locally on the machine to prevent data leaks."
            },
            {
                "question": "Does OmniDoc support image files?",
                "ground_truth": "The text only mentions PDF, DOCX, and URL support. It does not explicitly mention image files."
            }
        ]
        return source_text, qa_pairs

    def judge_faithfulness(self, context, answer):
        """
        Judge 1: Hallucination Check.
        Does the answer contain information NOT supported by the context?
        """
        prompt = (
            f"You are a strict judge. \n"
            f"Context: {context}\n"
            f"Answer: {answer}\n"
            f"Does the Answer contain any facts that are NOT found in the Context? "
            f"Reply with exactly 'YES' (it hallucinates) or 'NO' (it is faithful)."
        )
        response = self.llm.invoke(prompt).content.strip().upper()
        # If response contains NO, it's faithful (Score 1.0). If YES, it hallucinates (Score 0.0)
        return 1.0 if "NO" in response else 0.0

    def judge_correctness(self, ground_truth, answer):
        """
        Judge 2: Accuracy Check.
        Does the generated answer match the meaning of the ground truth?
        """
        prompt = (
            f"Compare these two answers:\n"
            f"Ground Truth: {ground_truth}\n"
            f"Generated: {answer}\n"
            f"Do they match in meaning? Reply with a score from 1 to 5, where 5 is perfect match."
        )
        response = self.llm.invoke(prompt).content.strip()
        # Extract number
        try:
            score = int(''.join(filter(str.isdigit, response))[0])
            return score
        except:
            return 3 # Default if parsing fails

    def run_eval(self):
        print(f"Starting Quality Evaluation using model: {self.model_name}...")
        source_text, dataset = self.get_eval_dataset()

        # 1. Build Index
        print("Building Index from Ground Truth Text...")
        docs = [Document(page_content=source_text, metadata={"source": "gold_standard"})]
        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        splits = splitter.split_documents(docs)
        vectorstore = app2.build_vectorstore(splits)
        retriever = vectorstore.as_retriever()

        results = []

        print("\nEvaluating Queries...")
        for item in dataset:
            q = item['question']
            gt = item['ground_truth']
            
            # Run RAG
            # Using context-only generation for tighter control
            # Try to use app2 function, fallback to manual chain if needed
            try:
                style = {"brief": True}
                # Emulate finding context
                retrieved_docs = retriever.invoke(q)
                context_str = "\n".join([d.page_content for d in retrieved_docs])
                
                # Check directly with LLM to simulate app's response
                prompt = app2.build_prompt(context_str, q, style) if hasattr(app2, 'build_prompt') else f"Context: {context_str}\nQuestion: {q}"
                gen_resp = self.llm.invoke(prompt)
                answer = getattr(gen_resp, "content", str(gen_resp))
                
            except Exception as e:
                print(f"Error processing query '{q}': {e}")
                continue

            # Grading
            faithfulness_score = self.judge_faithfulness(context_str, answer)
            correctness_score = self.judge_correctness(gt, answer)

            results.append({
                "question": q,
                "answer": answer,
                "faithfulness": faithfulness_score, # 1.0 = good, 0.0 = hallucination
                "correctness": correctness_score    # 1-5 scale
            })
            print(f"  Q: {q[:30]}... -> Faithfulness: {faithfulness_score}, Correctness: {correctness_score}/5")

        self.print_report(results)

    def print_report(self, results):
        print("\n" + "="*self.console_width)
        print("OMNIDOC AI - QUALITY & HALLUCINATION REPORT".center(self.console_width))
        print("="*self.console_width)
        
        avg_faith = sum(r['faithfulness'] for r in results) / len(results) if results else 0
        avg_corr = sum(r['correctness'] for r in results) / len(results) if results else 0
        
        print(f"{'Metric':<30} | {'Score':<10} | {'Interpretation'}")
        print("-" * self.console_width)
        print(f"{'Hallucination Resistance':<30} | {avg_faith*100:.1f}%      | (Higher is better)")
        print(f"{'Answer Accuracy (1-5)':<30} | {avg_corr:.1f}/5.0      | (Against Ground Truth)")
        print("-" * self.console_width)
        
        print("\n[Comparison to Existing Solutions]")
        print("Why OmniDoc is useful compared to ChatGPT/Claude (Cloud):")
        print("1. Privacy: 100% Local. No data leaves this i3 laptop.")
        print("2. Specialized Context: It answers based ONLY on your documents (Strict RAG).")
        print("   Other tools might mix general knowledge, leading to more hallucinations.")
        print(f"   Your Faithfulness Score of {avg_faith*100:.0f}% indicates how strict it is.")
        print("3. Cost: Zero API fees.")

if __name__ == "__main__":
    # Ensure Ollama is running before starting
    evaluator = QualityEvaluator() # Modify model name if needed
    evaluator.run_eval()