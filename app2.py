# Import necessary libraries for the app
import streamlit as st  # Streamlit library to build the web interface
import tempfile  # For creating temporary files during processing
import os  # For operating system interactions like environment variables
import threading  # For running speech in background
import re  # For regular expressions in URL parsing and style detection
import requests  # For making HTTP requests to fetch URLs
import hashlib  # For generating cache keys
from pdf2image.exceptions import PDFInfoNotInstalledError  # Exception for PDF processing errors
from langchain_community.document_loaders import UnstructuredPDFLoader, Docx2txtLoader, WebBaseLoader  # Loaders for different document types
#streamlit run app2.py  # Comment indicating how to run the app
try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter  # Newer version of text splitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter  # Fallback for older version
from langchain_huggingface import HuggingFaceEmbeddings  # For generating embeddings
from langchain_community.vectorstores import FAISS  # Vector store for similarity search
from langchain_ollama import ChatOllama  # Ollama integration for LLM

# Voice input support
from streamlit_mic_recorder import speech_to_text  # For voice input

# Text-to-Speech (offline)
import pyttsx3  # For text-to-speech functionality
from typing import List  # Type hints
import json  # For handling JSON data in history
from datetime import datetime  # For timestamps
import uuid  # For unique IDs in history

# Set Poppler path for Windows PDF processing
POPPLER_PATH = r"C:\poppler-25.07.0\Library\bin"  # Path to Poppler binaries for PDF to image conversion
os.environ["POPPLER_PATH"] = POPPLER_PATH  # Set environment variable for Poppler
os.environ.setdefault("USER_AGENT", "OmniDocAI/1.0 (+http://localhost)")  # Default user agent for requests
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")  # Ollama server URL
COMTYPES_GEN_DIR = os.path.join(tempfile.gettempdir(), "comtypes_gen")
os.makedirs(COMTYPES_GEN_DIR, exist_ok=True)
os.environ.setdefault("COMTYPES_GEN_DIR", COMTYPES_GEN_DIR)

# Initialize TTS engine lazily (Windows COM/SAPI requires thread init)
tts_engine = None  # Global TTS engine variable

# Global flag to control speech
stop_speaking = False  # Flag to stop speech playback

# Function to extract text from PDF files
# Uses UnstructuredPDFLoader with pdf2image for OCR, falls back to pdfminer if needed
def extract_text_from_pdf(uploaded_file):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:  # Create temp file to save uploaded PDF
        tmp_file.write(uploaded_file.read())
        tmp_file_path = tmp_file.name
    try:
        loader = UnstructuredPDFLoader(  # Use OCR loader for scanned PDFs
            tmp_file_path,
            unstructured_kwargs={"pdf_extractor": "pdf2image"}
        )
        docs = loader.load()
    except (PDFInfoNotInstalledError, FileNotFoundError, RuntimeError):  # If OCR fails, use text extractor
        # Fallback if Poppler or OCR path not available
        loader = UnstructuredPDFLoader(
            tmp_file_path,
            unstructured_kwargs={"pdf_extractor": "pdfminer"}
        )
        docs = loader.load()
    finally:
        os.unlink(tmp_file_path)  # Delete temp file after processing
    return docs

# Function to extract text from DOCX files
def extract_text_from_docx(uploaded_file):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp_file:  # Create temp file for DOCX
        tmp_file.write(uploaded_file.read())
        tmp_file_path = tmp_file.name

    loader = Docx2txtLoader(tmp_file_path)  # Load DOCX content
    docs = loader.load()
    os.unlink(tmp_file_path)  # Clean up temp file
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
    """Set flag to stop speech"""
    global stop_speaking
    stop_speaking = True

def reset_speech():
    """Reset stop flag for next speech"""
    global stop_speaking
    stop_speaking = False

def fetch_google_drive_file(url):
    """Download a publicly shared Google Drive file (PDF/DOCX) and return bytes + inferred extension."""
    # Patterns:
    # https://drive.google.com/file/d/<FILEID>/view?usp=sharing
    # https://drive.google.com/uc?id=<FILEID>&export=download
    file_id_match = re.search(r"/d/([A-Za-z0-9_-]+)", url)  # Extract file ID from URL
    if not file_id_match:
        file_id_match = re.search(r"[?&]id=([A-Za-z0-9_-]+)", url)
    if not file_id_match:
        raise ValueError("Could not extract Google Drive file ID.")
    file_id = file_id_match.group(1)
    direct_url = f"https://drive.google.com/uc?export=download&id={file_id}"  # Direct download URL
    resp = requests.get(direct_url, stream=True)  # Download the file
    if resp.status_code != 200:
        raise ValueError(f"Download failed (status {resp.status_code}). File may not be public.")
    content_type = resp.headers.get("Content-Type", "").lower()  # Check file type
    if "pdf" in content_type:
        ext = ".pdf"
    elif "word" in content_type or "docx" in content_type:
        ext = ".docx"
    else:
        # Try to guess from link (fallback)
        ext = ".pdf" if "pdf" in url.lower() else ".docx"
    return resp.content, ext

def extract_from_raw_bytes(raw_bytes, ext):
    """Route raw bytes to existing extractors."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:  # Create temp file from bytes
        tmp.write(raw_bytes)
        path = tmp.name
    try:
        if ext == ".pdf":
            loader = UnstructuredPDFLoader(path, unstructured_kwargs={"pdf_extractor": "pdf2image"})  # Use PDF loader
        else:
            loader = Docx2txtLoader(path)  # Use DOCX loader
        docs = loader.load()
    finally:
        os.unlink(path)  # Clean up temp file
    return docs

def fetch_google_docs(url):
    """Convert Google Docs share link to exportable format and fetch as text."""
    # Extract document ID from various Google Docs URL formats
    doc_id_match = re.search(r'/document/d/([a-zA-Z0-9-_]+)', url)
    if not doc_id_match:
        raise ValueError("Could not extract Google Docs document ID from URL.")
    
    doc_id = doc_id_match.group(1)
    
    # Convert to export URL (plain text format)
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    
    headers = {
        "User-Agent": "ChatDocBot/1.0 (+https://github.com/YourUser/YourRepo)",  # Custom user agent
    }
    
    resp = requests.get(export_url, headers=headers)
    if resp.status_code != 200:
        raise ValueError(f"Failed to fetch Google Docs (status {resp.status_code}). Document may not be public.")
    
    # Create a document object similar to other loaders
    from langchain.schema import Document
    content = resp.text
    return [Document(page_content=content, metadata={"source": url, "type": "google_docs"})]

def fetch_url_documents(url):
    url = (url or "").strip()  # Clean the URL
    if not url:
        return []
    if "docs.google.com/document" in url:  # Check if it's Google Docs
        return fetch_google_docs(url)
    if "drive.google.com" in url:  # Check if it's Google Drive
        raw, ext = fetch_google_drive_file(url)
        return extract_from_raw_bytes(raw, ext)
    if not re.match(r"^https?://", url):  # Add protocol if missing
        if url.startswith("www."):
            url = "https://" + url
        else:
            url = "https://" + url
    headers = {"User-Agent": os.environ.get("USER_AGENT", "OmniDocAI/1.0")}  # Set user agent
    resp = None
    try:
        resp = requests.get(url, headers=headers, timeout=20, stream=True)  # Try HTTPS
    except Exception:
        if url.startswith("https://"):  # Fallback to HTTP
            try:
                alt = "http://" + url[len("https://"):]
                resp = requests.get(alt, headers=headers, timeout=20, stream=True)
                url = alt
            except Exception:
                loader = WebBaseLoader(  # Use web loader as last resort
                    url,
                    header_template={
                        "User-Agent": headers["User-Agent"],
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                )
                return loader.load()
    if resp is None:  # If no response, use web loader
        loader = WebBaseLoader(
            url,
            header_template={
                "User-Agent": headers["User-Agent"],
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        return loader.load()
    if resp.status_code != 200:  # Check for success
        raise ValueError(f"Failed to download URL (status {resp.status_code}).")
    content_type = resp.headers.get("Content-Type", "").lower()  # Get content type
    lowered = url.lower()
    if "pdf" in content_type or lowered.endswith(".pdf"):  # If PDF
        return extract_from_raw_bytes(resp.content, ".pdf")
    if "word" in content_type or "officedocument" in content_type or lowered.endswith(".docx"):  # If DOCX
        return extract_from_raw_bytes(resp.content, ".docx")
    from langchain.schema import Document  # For plain text
    text = resp.text
    return [Document(page_content=text, metadata={"source": url})]

def build_vectorstore(docs):
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)  # Split text into chunks
    chunks = text_splitter.split_documents(docs)  # Create overlapping chunks
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")  # Generate embeddings
    return FAISS.from_documents(chunks, embeddings)  # Build FAISS vector store

# def generate_answer_with_context(llm, retriever, query, k: int = 4):
#     docs = retriever.invoke(query)  # Retrieve relevant documents
#     if not isinstance(docs, list):
#         docs = [docs]
#     context = "\n\n".join(d.page_content for d in docs[:k])  # Combine context
#     prompt = (
#         "You are an assistant that answers based only on the provided context.\n\n"
#         + "Context:\n" + context + "\n\n"
#         + "Question:\n" + query + "\n\n"
#         + "Answer concisely. If the answer is not in the context, say: I don't know based on the provided documents."
#     )
#     try:
#         resp = llm.invoke(prompt)  # Generate answer with LLM
#         answer = getattr(resp, "content", str(resp))
#         return answer, docs
#     except Exception:
#         return generate_answer_from_context_only(retriever, query, k)  # Fallback

def generate_answer_from_context_only(retriever, query, k: int = 4):
    docs = retriever.invoke(query)  # Retrieve docs
    if not isinstance(docs, list):
        docs = [docs]
    context = "\n\n".join(d.page_content for d in docs[:k])  # Get context
    snippet = context[:600]  # Limit length
    return snippet, docs

def detect_style(q: str):
    s = {"points": None, "brief": False}  # Initialize style dict
    m = re.search(r"(\d{1,2})\s*(marks?|points?)", q, flags=re.I)  # Check for points
    if m:
        try:
            s["points"] = int(m.group(1))
        except Exception:
            s["points"] = None
    if re.search(r"\bbrief(ly)?\b|\bshort\b|\bsummar(y|ize)\b", q, flags=re.I):  # Check for brief
        s["brief"] = True
    return s

def build_prompt(context: str, query: str, style: dict):
    if style.get("points"):  # If points specified
        n = style["points"]
        return (
            "Use only the context to answer.\n\nContext:\n" + context + "\n\n" +
            "Instruction: Write exactly " + str(n) + " bullet points. One concise sentence per point. No extra text.\n" +
            "Question:\n" + query
        )
    if style.get("brief"):  # If brief requested
        return (
            "Use only the context to answer.\n\nContext:\n" + context + "\n\n" +
            "Instruction: Write a brief 3-5 sentence summary, concise and precise.\n" +
            "Question:\n" + query
        )
    return (  # Default prompt
        "Use only the context to answer.\n\nContext:\n" + context + "\n\n" +
        "Question:\n" + query + "\n\n" +
        "Respond clearly. If not in context, say: I don't know based on the provided documents."
    )

def generate_answer_with_style(llm, retriever, query, style, k: int = 8):
    docs = retriever.invoke(query)  # Retrieve docs
    if not isinstance(docs, list):
        docs = [docs]
    context = "\n\n".join(d.page_content for d in docs[:k])  # Build context
    prompt = build_prompt(context, query, style)  # Create prompt
    try:
        resp = llm.invoke(prompt)  # Generate with LLM
        answer = getattr(resp, "content", str(resp))
        return answer, docs
    except Exception:
        return generate_answer_from_context_only_with_style(retriever, query, style, k)  # Fallback

def generate_answer_from_context_only_with_style(retriever, query, style, k: int = 8):
    docs = retriever.invoke(query)  # Retrieve docs
    if not isinstance(docs, list):
        docs = [docs]
    context = "\n".join(d.page_content for d in docs[:k])  # Get context
    if style.get("points"):  # For points style
        n = style["points"]
        parts = re.split(r"[\n\.;]\s+", context)  # Split into parts
        items = [p.strip() for p in parts if len(p.strip()) > 0][:max(n, 1)]  # Get items
        bullets = items[:n]
        ans = "\n".join(["- " + b for b in bullets])  # Format bullets
        return ans, docs
    if style.get("brief"):  # For brief style
        parts = re.split(r"[\n\.;]\s+", context)  # Split
        short = " ".join(parts[:4])  # Take first parts
        return short[:600], docs  # Limit length
    return context[:700], docs  # Default

def is_ollama_available(base_url: str) -> bool:
    try:
        r = requests.get(base_url.rstrip("/") + "/api/tags", timeout=2)  # Check Ollama API
        return r.status_code == 200  # Return true if available
    except Exception:
        return False  # False if not

def cache_key(docs):
    h = hashlib.sha256()  # Create hash object
    for d in docs:
        h.update(str(len(d.page_content)).encode())  # Hash length
        h.update(d.page_content[:200].encode(errors="ignore"))  # Hash start of content
    return h.hexdigest()  # Return hash as key

def save_search_history(query, answer, lang, sources_count=0):
    """Save search query and answer to session state and optionally to file."""
    if "search_history" not in st.session_state:  # Init if not exists
        st.session_state.search_history = []
    
    history_entry = {  # Create entry
        "id": str(uuid.uuid4()),        # <— add unique id
        "timestamp": datetime.now().isoformat(),
        "query": query,
        "answer": answer,
        "language": lang,
        "sources_count": sources_count
    }
    
    st.session_state.search_history.append(history_entry)  # Add to session
    
    # Optional: Save to file for persistence across sessions
    try:
        with open("search_history.json", "w", encoding="utf-8") as f:  # Save to file
            json.dump(st.session_state.search_history, f, ensure_ascii=False, indent=2)
    except:
        pass  # Ignore file save errors

def delete_history_entry(entry_id: str):
    """Delete single history entry by id."""
    if "search_history" in st.session_state:  # If history exists
        st.session_state.search_history = [  # Filter out the entry
            h for h in st.session_state.search_history if h.get("id") != entry_id
        ]
        # persist
        try:
            with open("search_history.json", "w", encoding="utf-8") as f:  # Update file
                json.dump(st.session_state.search_history, f, ensure_ascii=False, indent=2)
        except:
            pass

def load_search_history():
    """Load search history from file if it exists."""
    try:
        with open("search_history.json", "r", encoding="utf-8") as f:  # Open file
            data = json.load(f)  # Load JSON
            # Backfill ids for legacy entries
            changed = False
            for entry in data:
                if "id" not in entry:
                    entry["id"] = str(uuid.uuid4())  # Add id if missing
                    changed = True
            if changed:
                try:
                    with open("search_history.json", "w", encoding="utf-8") as wf:  # Save back
                        json.dump(data, wf, ensure_ascii=False, indent=2)
                except:
                    pass
            return data
    except:
        return []  # Return empty if error

def ensure_history_ids():
    """Ensure all in-memory history entries have an id (for sessions created before id support)."""
    if "search_history" in st.session_state:  # If history exists
        changed = False
        for entry in st.session_state.search_history:
            if "id" not in entry:
                entry["id"] = str(uuid.uuid4())  # Add id
                changed = True
        if changed:
            try:
                with open("search_history.json", "w", encoding="utf-8") as f:  # Save
                    json.dump(st.session_state.search_history, f, ensure_ascii=False, indent=2)
            except:
                pass

def display_search_history():
    """Display search history in expandable sections."""
    if "search_history" not in st.session_state or not st.session_state.search_history:  # If no history
        st.info("No search history yet.")
        return

    ensure_history_ids()  # Ensure ids
    st.write(f"**Total searches:** {len(st.session_state.search_history)}")  # Show count

    recent_history = st.session_state.search_history[-10:][::-1]  # Get recent 10 reversed
    for idx, entry in enumerate(recent_history):
        entry_id = entry.get("id", str(uuid.uuid4()))  # Get id
        entry["id"] = entry_id
        timestamp = datetime.fromisoformat(entry["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")  # Format time
        with st.expander(f"🔍 {entry['query'][:50]}... - {timestamp}"):  # Expander
            st.write(f"**Language:** {entry['language']}")
            st.write(f"**Query:** {entry['query']}")
            st.write(f"**Answer:** {entry['answer']}")
            st.write(f"**Sources used:** {entry['sources_count']}")
            cols = st.columns(3)  # Buttons
            with cols[0]:
                if st.button("🔄 Reuse", key=f"reuse_{entry_id}"):
                    st.session_state.reused_query = entry['query']
                    st.rerun()
            with cols[1]:
                if st.button("🗑️ Delete", key=f"del_{entry_id}"):
                    delete_history_entry(entry_id)
                    st.rerun()
            with cols[2]:
                st.caption(entry_id)

def clear_search_history():
    """Clear all search history."""
    st.session_state.search_history = []  # Clear session
    try:
        if os.path.exists("search_history.json"):  # If file exists
            os.remove("search_history.json")  # Delete file
    except:
        pass

def export_search_history():
    """Export search history as downloadable JSON."""
    if "search_history" not in st.session_state or not st.session_state.search_history:  # If no history
        return None  # Return none
    
    history_json = json.dumps(st.session_state.search_history, ensure_ascii=False, indent=2)  # Dump to JSON
    return history_json.encode('utf-8')  # Return bytes

def main():
    st.title("OmniDoc AI: The Universal Document Intelligence Assistant")  # Set app title

    # Initialize session state
    if "docs" not in st.session_state:  # Init docs list
        st.session_state.docs = []
    if "processed_files" not in st.session_state:  # Init processed files
        st.session_state.processed_files = []
    if "vectordb" not in st.session_state:  # Init vector db
        st.session_state.vectordb = None
    if "vectordb_key" not in st.session_state:  # Init cache key
        st.session_state.vectordb_key = None
    if "search_history" not in st.session_state:  # Init history
        st.session_state.search_history = load_search_history()
    ensure_history_ids()  # Ensure ids
    if "reused_query" not in st.session_state:  # Init reused query
        st.session_state.reused_query = ""

    # Sidebar for search history
    with st.sidebar:
        st.header("🔍 Search History")  # Header
        
        # History stats
        if st.session_state.search_history:
            total_searches = len(st.session_state.search_history)  # Count
            st.metric("Total Searches", total_searches)  # Show metric
            
            # Recent queries preview
            if st.checkbox("Show Recent Queries"):  # Checkbox
                recent = st.session_state.search_history[-5:][::-1]  # Get recent
                for entry in recent:
                    timestamp = datetime.fromisoformat(entry["timestamp"]).strftime("%m-%d %H:%M")  # Format
                    st.text(f"{timestamp}: {entry['query'][:30]}...")  # Show
        
        # History management buttons
        col1, col2 = st.columns(2)  # Columns
        with col1:
            if st.button("📋 View All"):  # View button
                st.session_state.show_history = True
        with col2:
            if st.button("🗑️ Clear"):  # Clear button
                clear_search_history()
                st.success("History cleared!")  # Success
                st.rerun()
        
        # Export history
        if st.session_state.search_history:
            history_data = export_search_history()  # Get data
            if history_data:
                st.download_button(  # Download button
                    label="💾 Export History",
                    data=history_data,
                    file_name=f"search_history_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
                    mime="application/json"
                )

    lang_choice = st.selectbox("Interaction language", ["English", "Kannada"], index=0)  # Language select
    # Model selection (fast vs larger)
    model_choice = st.selectbox(
        "Ollama Model",
        ["llama3.2:3b", "llama3.1:8b"],
        index=0,
        help="llama3.2:3b = faster & smaller, llama3.1:8b = higher quality"
    )  # Model select
    st.session_state["ollama_model"] = model_choice  # Store model

    uploaded_file = st.file_uploader("Upload a PDF or Word document", type=["pdf", "docx"])  # File uploader
    url_input = st.text_input("Or enter a web / Google Drive link (public):")  # URL input
    fetch_clicked = st.button("Fetch URL")  # Fetch button

    docs_changed = False  # Flag for changes

    # Handle new file upload only once
    if uploaded_file and uploaded_file.name not in st.session_state.processed_files:  # If new file
        ext = uploaded_file.name.split('.')[-1].lower()  # Get extension
        if ext == "pdf":
            with st.spinner("Extracting text from uploaded PDF..."):  # Spinner
                st.session_state.docs.extend(extract_text_from_pdf(uploaded_file))  # Extract
        elif ext == "docx":
            with st.spinner("Extracting text from uploaded DOCX..."):  # Spinner
                st.session_state.docs.extend(extract_text_from_docx(uploaded_file))  # Extract
        st.session_state.processed_files.append(uploaded_file.name)  # Mark processed
        docs_changed = True  # Set flag

    # URL fetch
    if fetch_clicked and url_input:  # If fetch clicked
        try:
            with st.spinner("Fetching URL content..."):  # Spinner
                fetched = fetch_url_documents(url_input)  # Fetch
                st.session_state.docs.extend(fetched)  # Add
                st.success(f"Fetched {len(fetched)} chunk(s) from URL.")  # Success
                docs_changed = True  # Set flag
        except Exception as e:
            st.error(f"URL fetch failed: {e}")  # Error

    docs = st.session_state.docs  # Get docs

    # Show full history if requested
    if hasattr(st.session_state, 'show_history') and st.session_state.show_history:  # If show history
        st.header("📜 Complete Search History")  # Header
        display_search_history()  # Display
        if st.button("❌ Close History"):  # Close button
            st.session_state.show_history = False
            st.rerun()
        st.divider()  # Divider

    if docs:  # If docs exist
        # Build / rebuild vector store only when docs changed
        if docs_changed:  # If changed
            with st.spinner("Building / updating vector index..."):  # Spinner
                key = cache_key(docs)  # Get key
                st.session_state.vectordb = build_vectorstore(docs)  # Build
                st.session_state.vectordb_key = key  # Store key
        elif st.session_state.vectordb is None:  # If not built
            with st.spinner("Building vector index..."):  # Spinner
                key = cache_key(docs)  # Get key
                st.session_state.vectordb = build_vectorstore(docs)  # Build
                st.session_state.vectordb_key = key  # Store key

        vectordb = st.session_state.vectordb  # Get db

        st.write("### Document preview:")  # Preview header
        preview_text = "\n\n".join(d.page_content for d in docs[:2])  # Get preview
        st.text_area("Preview (first documents, truncated):", preview_text[:1000] + "...", height=200)  # Show preview

        # Use selected model (with Ollama availability check)
        selected_model = st.session_state.get("ollama_model", "llama3.2:3b")  # Get model
        llm = None  # Init llm
        if is_ollama_available(OLLAMA_HOST):  # If available
            llm = ChatOllama(  # Create llm
                model=selected_model,
                temperature=0,
                num_ctx=2048,
                num_predict=512,
                base_url=OLLAMA_HOST
            )
            st.caption(f"Using model: {selected_model} via {OLLAMA_HOST}")  # Caption
        else:
            st.warning("Ollama server not reachable. Answers will be based on document excerpts without generation.")  # Warning
        retriever = vectordb.as_retriever(search_type="mmr", search_kwargs={"k": 8, "fetch_k": 24, "lambda_mult": 0.5})  # Create retriever

        col1, col2 = st.columns([1, 8])  # Columns for voice
        with col1:
            st.markdown('<span title="Record your voice question"><span style="font-size:35px; cursor:pointer;">🎤</span></span>', unsafe_allow_html=True)  # Voice icon
        with col2:
            st.write("Ask by voice or type:")  # Label

        if lang_choice == "Kannada":  # If Kannada
            voice_query = speech_to_text(language='kn', just_once=False, key='voice_input')  # Voice input
        else:
            voice_query = speech_to_text(language='en', just_once=False, key='voice_input')  # Voice input

        # Handle reused query from history
        if st.session_state.reused_query:  # If reused
            query = st.text_input("Type your question:", value=st.session_state.reused_query, key="type_box")  # Input with value
            st.session_state.reused_query = ""  # Clear
        elif voice_query:  # If voice
            query = st.text_input("Recognized voice input:", value=voice_query, key="voice_box")  # Input with voice
        else:
            query = st.text_input("Type your question:", key="type_box")  # Normal input

        final_query = query.strip()  # Strip query

        if final_query:  # If query exists
            retrieval_query = final_query  # Init retrieval
            if lang_choice == "Kannada" and llm is not None:  # If Kannada and llm
                try:
                    trans_q = llm.invoke("Translate the following Kannada question to English. Reply ONLY with the English translation:\n\n" + final_query)  # Translate
                    retrieval_query = getattr(trans_q, "content", str(trans_q))  # Get translation
                except Exception:
                    retrieval_query = final_query  # Fallback

            style = detect_style(final_query)  # Detect style
            with st.spinner("Generating answer..."):  # Spinner
                if llm is not None:  # If llm available
                    answer, sources = generate_answer_with_style(llm, retriever, retrieval_query, style, k=8)  # Generate with llm
                else:
                    answer, sources = generate_answer_from_context_only_with_style(retriever, retrieval_query, style, k=8)  # Fallback

            if lang_choice == "Kannada" and llm is not None:  # If Kannada
                try:
                    trans_a = llm.invoke("Translate the following answer to Kannada. Reply ONLY with the Kannada translation:\n\n" + answer)  # Translate answer
                    answer = getattr(trans_a, "content", str(trans_a))  # Get translation
                except Exception:
                    pass  # Skip

            st.write("*Answer:*", answer)  # Show answer

            # Save to search history
            save_search_history(final_query, answer, lang_choice, len(sources))  # Save

            if sources:  # If sources
                with st.expander("Sources"):  # Expander
                    for i, src in enumerate(sources, 1):  # Loop sources
                        snippet = src.page_content[:350].replace("\n", " ")  # Get snippet
                        st.markdown(f"**{i}.** {snippet}...")  # Show

            c1, c2 = st.columns([1, 1])  # Columns for buttons
            with c1:
                if st.button("🔊 Hear Answer"):
                    if ensure_tts_engine():
                        reset_speech()
                        threading.Thread(target=speak_text, args=(answer,), daemon=True).start()
                    else:
                        st.warning("Voice output is unavailable on this system.")
            with c2:
                if st.button("🛑 Stop Hearing"):  # Stop button
                    stop_speech()  # Stop
    else:
        st.info("Upload a file or fetch a URL to begin.")  # Info message if no docs

if __name__ == "__main__":
    main()  # Run the main function