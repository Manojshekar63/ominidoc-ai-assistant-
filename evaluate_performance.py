import time
import os
import sys
import io
import threading
from typing import List, Dict, Any
from unittest.mock import MagicMock
import types
from langchain_core.documents import Document
try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain_community.document_transformers import RecursiveCharacterTextSplitter

# Ensure this script's directory is on sys.path so app2.py can be imported reliably
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

# Robust Streamlit mock BEFORE importing app2 to avoid import-time failures
# (creates minimal package + components.v1 expected by streamlit_mic_recorder)
streamlit_mod = types.ModuleType("streamlit")
components_mod = types.ModuleType("streamlit.components")
components_v1 = types.ModuleType("streamlit.components.v1")
# minimal fakes commonly used at import time
components_v1.declare_component = lambda *a, **k: MagicMock()
components_v1.html = lambda *a, **k: None
components_mod.v1 = components_v1
streamlit_mod.components = components_mod
# basic st functions used at import time
streamlit_mod.session_state = {}
streamlit_mod.write = lambda *a, **k: None
streamlit_mod.empty = lambda *a, **k: MagicMock()
streamlit_mod.sidebar = types.SimpleNamespace()
# install into sys.modules
sys.modules["streamlit"] = streamlit_mod
sys.modules["streamlit.components"] = components_mod
sys.modules["streamlit.components.v1"] = components_v1

# Robust import of app2: try normal import first, then fallback to loading by file path
try:
    import importlib
    app2 = importlib.import_module("app2")
except Exception:
    import importlib.util
    app2_path = os.path.join(script_dir, "app2.py")
    if not os.path.exists(app2_path):
        print("Error: Could not find app2.py in the project directory.")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("app2", app2_path)
    app2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app2)

# Re-ensure mock if import reloaded it (unlikely but safe)
app2.st = sys.modules["streamlit"]

class PerformanceEvaluator:
    def __init__(self):
        self.results = []
        self.console_width = 60

    def log_result(self, stage: str, duration: float, notes: str = ""):
        self.results.append({
            "Stage": stage,
            "Duration (s)": round(duration, 4),
            "Notes": notes
        })
        print(f"✅ {stage:<25} | {duration:.4f}s | {notes}")

    def create_synthetic_docs(self, num_pages=5, sentences_per_page=20) -> List[Any]:
        """Creates synthetic Document objects to simulate extracted text."""
        print(f"\nGeneratng synthetic data ({num_pages} pages)...")
        docs = []
        base_text = "This is a sentence about performance evaluation in Python. " \
                    "The OmniDoc AI project aims to analyze documents efficiently. " \
                    "Performance metrics include latency, throughput, and resource usage. " \
                    "We use embedding models like HuggingFace and LLMs like Llama 3. " \
                    "Streamlit provides a fast way to build data apps. "
        
        for i in range(num_pages):
            page_content = (base_text * sentences_per_page) + f" [End of page {i+1}]"
            docs.append(Document(page_content=page_content, metadata={"source": f"synthetic_page_{i+1}.pdf"}))
        return docs

    def run_benchmark(self):
        print("="*self.console_width)
        print("OMNIDOC AI PERFORMANCE BENCHMARK".center(self.console_width))
        print("="*self.console_width)
        print(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("-" * self.console_width)

        # 1. Test Data Generation (Baseline)
        start_time = time.perf_counter()
        docs = self.create_synthetic_docs(num_pages=5, sentences_per_page=15)
        self.log_result("Synthetic Data Gen", time.perf_counter() - start_time, f"{len(docs)} pages created")

        # 2. Vector Store Build Time
        # This tests Embedding (HuggingFace) + Indexing (FAISS)
        print("\n[Running] Building Vector Store (may take time on i3 CPU)...")
        start_time = time.perf_counter()
        try:
            # Emulate the chunking process typically found in the main app
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
            splits = text_splitter.split_documents(docs)
            print(f"   Splitted into {len(splits)} chunks.")

            vectorstore = app2.build_vectorstore(splits)
            duration = time.perf_counter() - start_time
            self.log_result("Vector Store Build", duration, f"Embeddings + FAISS ({len(splits)} chunks)")
        except Exception as e:
            print(f"❌ Vector Store Build Failed: {e}")
            return

        # 3. Retrieval Performance
        # Create a retriever from the vectorstore
        retriever = vectorstore.as_retriever()
        query = "What represents performance evaluation?"
        
        print("\n[Running] Retrieval Test...")
        start_time = time.perf_counter()
        retrieved_docs = retriever.invoke(query)
        duration = time.perf_counter() - start_time
        self.log_result("Context Retrieval", duration, f"Retrieved {len(retrieved_docs)} docs")

        # 4. LLM Response Generation (Mocked if Ollama not active, or attempted)
        # We'll try to use the real one if possible, assuming user has Ollama running.
        # If it fails, we catch it.
        print("\n[Running] LLM Generation Test (Ollama)...")
        print("Note: This depends heavily on your local Ollama model (e.g., llama3.2).")
        
        llm = None
        try:
            # Initialize LLM as done in app2
            # We assume "llama3.2:3b" or "llama3.1:8b" or "mistral" is available.
            # Only app2 defines the model name deep inside or via selection. 
            # Looking at app2 snippet, it imports ChatOllama but model name is likely passed or hardcoded?
            # app2.py snippet doesn't show model initialization in global scope. 
            # It's likely in main(). We'll instantiate one manually for the test.
            from langchain_ollama import ChatOllama
            llm = ChatOllama(model="llama3.2:3b", base_url=app2.OLLAMA_HOST)
            
            # Simple health check invocation
            start_time = time.perf_counter()
            # We use a simple prompt to minimize generation time for the test
            response = llm.invoke("Hi")
            duration = time.perf_counter() - start_time
            self.log_result("LLM Warmup (Hi)", duration, "Model Loading/Response")

            # Full RAG generation simulation
            # We use the function from app2: generate_answer_from_context_only_with_style
            # if available, or manually construct chain.
            # app2 has 'generate_answer_with_style'
            
            style = {"detail_level": "Concise", "tone": "Formal", "points": 0, "brief": False}
            print("\n[Running] Full RAG Generation...")
            start_time = time.perf_counter()
            # We used retrieval earlier, so we pass context
            # Simulating: generate_answer_with_style(llm, retriever, query, style)
            
            # Note: app2.generate_answer_with_style code was omitted in snippet, 
            # assuming it calls llm.invoke with a prompt built from docs.
            # We'll call it if it exists and takes these args.
            if hasattr(app2, 'generate_answer_with_style'):
                answer, used_docs = app2.generate_answer_with_style(llm, retriever, query, style)
                duration = time.perf_counter() - start_time
                self.log_result("Full RAG Chain", duration, "Retrieve + Generate")
            else:
                 self.log_result("Full RAG Chain", 0, "Skipped: Function not found")

        except Exception as e:
            print(f"⚠️ LLM Test Failed (is Ollama running?): {e}")
            self.log_result("LLM Generation", 0, "Failed/Skipped")

    def print_report(self):
        print("\n" + "="*self.console_width)
        print("PERFORMANCE EVALUATION REPORT".center(self.console_width))
        print("="*self.console_width)
        print(f"{'Stage':<25} | {'Duration':<10} | {'Notes'}")
        print("-" * self.console_width)
        
        total_time = 0
        for res in self.results:
            print(f"{res['Stage']:<25} | {res['Duration (s)']:<10.4f} | {res['Notes']}")
            total_time += res['Duration (s)']
            
        print("-" * self.console_width)
        print(f"{'Total Test Time':<25} | {total_time:<10.4f} |")
        print("="*self.console_width)
        print("\n[Recommendation]")
        print("If 'Vector Store Build' > 30s: Consider reducing chunk overlap or using a lighter embedding model.")
        print("If 'Full RAG Chain' > 10s: Consider using a quantized model (e.g. q4_0) or upgrade to GPU.")

if __name__ == "__main__":
    if not os.path.exists("app2.py"):
        print("Error: app2.py not found in current directory.")
    else:
        evaluator = PerformanceEvaluator()
        evaluator.run_benchmark()
