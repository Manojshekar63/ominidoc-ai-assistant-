# Import necessary libraries for the app
import streamlit as st
import tempfile
import os
import threading
import re
import requests
import hashlib
from pdf2image.exceptions import PDFInfoNotInstalledError
from langchain_community.document_loaders import UnstructuredPDFLoader, Docx2txtLoader, WebBaseLoader
try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_ollama import ChatOllama
from streamlit_mic_recorder import speech_to_text
import pyttsx3
from typing import List
import json
from datetime import datetime
import uuid

# Set Poppler path for Windows PDF processing
POPPLER_PATH = r"C:\poppler-25.07.0\Library\bin"
os.environ["POPPLER_PATH"] = POPPLER_PATH
os.environ.setdefault("USER_AGENT", "OmniDocAI/1.0 (+http://localhost)")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
COMTYPES_GEN_DIR = os.path.join(tempfile.gettempdir(), "comtypes_gen")
os.makedirs(COMTYPES_GEN_DIR, exist_ok=True)
os.environ.setdefault("COMTYPES_GEN_DIR", COMTYPES_GEN_DIR)

# Initialize TTS engine lazily
tts_engine = None
stop_speaking = False

# Function to extract text from PDF files
def extract_text_from_pdf(uploaded_file):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(uploaded_file.read())
        tmp_file_path = tmp_file.name
    try:
        loader = UnstructuredPDFLoader(tmp_file_path, unstructured_kwargs={"pdf_extractor": "pdf2image"})
        docs = loader.load()
    except (PDFInfoNotInstalledError, FileNotFoundError, RuntimeError):
        loader = UnstructuredPDFLoader(tmp_file_path, unstructured_kwargs={"pdf_extractor": "pdfminer"})
        docs = loader.load()
    finally:
        os.unlink(tmp_file_path)
    return docs

# Function to extract text from DOCX files
def extract_text_from_docx(uploaded_file):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp_file:
        tmp_file.write(uploaded_file.read())
        tmp_file_path = tmp_file.name
    loader = Docx2txtLoader(tmp_file_path)
    docs = loader.load()
    os.unlink(tmp_file_path)
    return docs

def speak_text(text):
    global stop_speaking, tts_engine
    try:
        import comtypes
        comtypes.CoInitialize()
        if tts_engine is None:
            tts_engine = pyttsx3.init(driverName='sapi5')
            tts_engine.setProperty('rate', 150)
            tts_engine.setProperty('volume', 0.9)
        engine = tts_engine
    except Exception:
        return
    if stop_speaking:
        return
    engine.say(text)
    try:
        engine.runAndWait()
    except:
        pass

def ensure_tts_engine():
    global tts_engine
    try:
        import comtypes
        comtypes.CoInitialize()
        if tts_engine is None:
            tts_engine = pyttsx3.init(driverName='sapi5')
            tts_engine.setProperty('rate', 150)
            tts_engine.setProperty('volume', 0.9)
        return True
    except Exception:
        tts_engine = None
        return False

def stop_speech():
    global stop_speaking
    stop_speaking = True

def reset_speech():
    global stop_speaking
    stop_speaking = False

def fetch_google_drive_file(url):
    file_id_match = re.search(r"/d/([A-Za-z0-9_-]+)", url)
    if not file_id_match:
        file_id_match = re.search(r"[?&]id=([A-Za-z0-9_-]+)", url)
    if not file_id_match:
        raise ValueError("Could not extract Google Drive file ID.")
    file_id = file_id_match.group(1)
    direct_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    resp = requests.get(direct_url, stream=True)
    if resp.status_code != 200:
        raise ValueError(f"Download failed (status {resp.status_code}). File may not be public.")
    content_type = resp.headers.get("Content-Type", "").lower()
    if "pdf" in content_type:
        ext = ".pdf"
    elif "word" in content_type or "docx" in content_type:
        ext = ".docx"
    else:
        ext = ".pdf" if "pdf" in url.lower() else ".docx"
    return resp.content, ext

def extract_from_raw_bytes(raw_bytes, ext):
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(raw_bytes)
        path = tmp.name
    try:
        if ext == ".pdf":
            loader = UnstructuredPDFLoader(path, unstructured_kwargs={"pdf_extractor": "pdf2image"})
        else:
            loader = Docx2txtLoader(path)
        docs = loader.load()
    finally:
        os.unlink(path)
    return docs

def fetch_google_docs(url):
    doc_id_match = re.search(r'/document/d/([a-zA-Z0-9-_]+)', url)
    if not doc_id_match:
        raise ValueError("Could not extract Google Docs document ID from URL.")
    doc_id = doc_id_match.group(1)
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    headers = {
        "User-Agent": "ChatDocBot/1.0 (+https://github.com/YourUser/YourRepo)",
    }
    resp = requests.get(export_url, headers=headers)
    if resp.status_code != 200:
        raise ValueError(f"Failed to fetch Google Docs (status {resp.status_code}). Document may not be public.")
    from langchain.schema import Document
    content = resp.text
    return [Document(page_content=content, metadata={"source": url, "type": "google_docs"})]

def fetch_url_documents(url):
    url = (url or "").strip()
    if not url:
        return []
    if "docs.google.com/document" in url:
        return fetch_google_docs(url)
    if "drive.google.com" in url:
        raw, ext = fetch_google_drive_file(url)
        return extract_from_raw_bytes(raw, ext)
    if not re.match(r"^https?://", url):
        if url.startswith("www."):
            url = "https://" + url
        else:
            url = "https://" + url
    headers = {"User-Agent": os.environ.get("USER_AGENT", "OmniDocAI/1.0")}
    resp = None
    try:
        resp = requests.get(url, headers=headers, timeout=20, stream=True)
    except Exception:
        if url.startswith("https://"):
            try:
                alt = "http://" + url[len("https://"):]
                resp = requests.get(alt, headers=headers, timeout=20, stream=True)
                url = alt
            except Exception:
                loader = WebBaseLoader(
                    url,
                    header_template={
                        "User-Agent": headers["User-Agent"],
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                )
                return loader.load()
    if resp is None:
        loader = WebBaseLoader(
            url,
            header_template={
                "User-Agent": headers["User-Agent"],
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        return loader.load()
    if resp.status_code != 200:
        raise ValueError(f"Failed to download URL (status {resp.status_code}).")
    content_type = resp.headers.get("Content-Type", "").lower()
    lowered = url.lower()
    if "pdf" in content_type or lowered.endswith(".pdf"):
        return extract_from_raw_bytes(resp.content, ".pdf")
    if "word" in content_type or "officedocument" in content_type or lowered.endswith(".docx"):
        return extract_from_raw_bytes(resp.content, ".docx")
    from langchain.schema import Document
    text = resp.text
    return [Document(page_content=text, metadata={"source": url})]

def build_vectorstore(docs):
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    chunks = text_splitter.split_documents(docs)
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    return FAISS.from_documents(chunks, embeddings)

def generate_answer_from_context_only(retriever, query, k: int = 4):
    docs = retriever.invoke(query)
    if not isinstance(docs, list):
        docs = [docs]
    context = "\n\n".join(d.page_content for d in docs[:k])
    snippet = context[:600]
    return snippet, docs

def detect_style(q: str):
    s = {"points": None, "brief": False}
    m = re.search(r"(\d{1,2})\s*(marks?|points?)", q, flags=re.I)
    if m:
        try:
            s["points"] = int(m.group(1))
        except Exception:
            s["points"] = None
    if re.search(r"\bbrief(ly)?\b|\bshort\b|\bsummar(y|ize)\b", q, flags=re.I):
        s["brief"] = True
    return s

def build_prompt(context: str, query: str, style: dict):
    if style.get("points"):
        n = style["points"]
        return (
            "Use only the context to answer.\n\nContext:\n" + context + "\n\n" +
            "Instruction: Write exactly " + str(n) + " bullet points. One concise sentence per point. No extra text.\n" +
            "Question:\n" + query
        )
    if style.get("brief"):
        return (
            "Use only the context to answer.\n\nContext:\n" + context + "\n\n" +
            "Instruction: Write a brief 3-5 sentence summary, concise and precise.\n" +
            "Question:\n" + query
        )
    return (
        "Use only the context to answer.\n\nContext:\n" + context + "\n\n" +
        "Question:\n" + query + "\n\n" +
        "Respond clearly. If not in context, say: I don't know based on the provided documents."
    )

def generate_answer_with_style(llm, retriever, query, style, k: int = 8):
    docs = retriever.invoke(query)
    if not isinstance(docs, list):
        docs = [docs]
    context = "\n\n".join(d.page_content for d in docs[:k])
    prompt = build_prompt(context, query, style)
    try:
        resp = llm.invoke(prompt)
        answer = getattr(resp, "content", str(resp))
        return answer, docs
    except Exception:
        return generate_answer_from_context_only(retriever, query, k)

def is_ollama_available(base_url: str) -> bool:
    try:
        r = requests.get(base_url.rstrip("/") + "/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False

def main():
    st.title("OmniDoc AI: The Universal Document Intelligence Assistant")

    if "docs" not in st.session_state:
        st.session_state.docs = []
    if "processed_files" not in st.session_state:
        st.session_state.processed_files = []
    if "vectordb" not in st.session_state:
        st.session_state.vectordb = None
    if "search_history" not in st.session_state:
        st.session_state.search_history = []

    uploaded_file = st.file_uploader("Upload a PDF or Word document", type=["pdf", "docx"])
    url_input = st.text_input("Or enter a web / Google Drive link (public):")
    fetch_clicked = st.button("Fetch URL")

    docs_changed = False

    if uploaded_file and uploaded_file.name not in st.session_state.processed_files:
        ext = uploaded_file.name.split('.')[-1].lower()
        if ext == "pdf":
            with st.spinner("Extracting text from uploaded PDF..."):
                st.session_state.docs.extend(extract_text_from_pdf(uploaded_file))
        elif ext == "docx":
            with st.spinner("Extracting text from uploaded DOCX..."):
                st.session_state.docs.extend(extract_text_from_docx(uploaded_file))
        st.session_state.processed_files.append(uploaded_file.name)
        docs_changed = True

    if fetch_clicked and url_input:
        try:
            with st.spinner("Fetching URL content..."):
                fetched = fetch_url_documents(url_input)
                st.session_state.docs.extend(fetched)
                st.success(f"Fetched {len(fetched)} chunk(s) from URL.")
                docs_changed = True
        except Exception as e:
            st.error(f"URL fetch failed: {e}")

    docs = st.session_state.docs

    if docs:
        if docs_changed:
            with st.spinner("Building / updating vector index..."):
                st.session_state.vectordb = build_vectorstore(docs)

        vectordb = st.session_state.vectordb

        st.write("### Document preview:")
        preview_text = "\n\n".join(d.page_content for d in docs[:2])
        st.text_area("Preview (first documents, truncated):", preview_text[:1000] + "...", height=200)

        selected_model = "llama3.2:3b"
        llm = None
        if is_ollama_available(OLLAMA_HOST):
            llm = ChatOllama(
                model=selected_model,
                temperature=0,
                num_ctx=2048,
                num_predict=512,
                base_url=OLLAMA_HOST
            )
            st.caption(f"Using model: {selected_model} via {OLLAMA_HOST}")
        else:
            st.warning("Ollama server not reachable. Answers will be based on document excerpts without generation.")
        retriever = vectordb.as_retriever(search_type="mmr", search_kwargs={"k": 8, "fetch_k": 24, "lambda_mult": 0.5})

        query = st.text_input("Type your question:", key="type_box")

        final_query = query.strip()

        if final_query:
            retrieval_query = final_query
            style = detect_style(final_query)
            with st.spinner("Generating answer..."):
                if llm is not None:
                    answer, sources = generate_answer_with_style(llm, retriever, retrieval_query, style, k=8)
                else:
                    answer, sources = generate_answer_from_context_only(retriever, retrieval_query, style, k=8)

            st.write("*Answer:*", answer)

            if sources:
                with st.expander("Sources"):
                    for i, src in enumerate(sources, 1):
                        snippet = src.page_content[:350].replace("\n", " ")
                        st.markdown(f"**{i}.** {snippet}...")

    else:
        st.info("Upload a file or fetch a URL to begin.")

if __name__ == "__main__":
    main()