from pydantic import BaseModel
from typing import Optional, List, Any, Dict

class HybridReq(BaseModel):
    query: str
    top_k: int = 5
    alpha: float = 0.5
    backend: Optional[str] = None   # override

class VectorReq(BaseModel):
    query: str
    top_k: int = 5
    backend: Optional[str] = None

class FtsReq(BaseModel):
    query: str
    top_k: int = 10
    mode: str = "both"   # documents | metadata | both
    backend: Optional[str] = None

class RagReq(BaseModel):
    question: str
    backend: Optional[str] = None
    llm_source: Optional[str] = None  # ollama | oci_genai | bedrock
    model: Optional[str] = None
    region: Optional[str] = None
    context_chunks: Optional[List[str]] = None
    sources: Optional[List[str]] = None
    chunk_metadata: Optional[List[Dict[str, Any]]] = None
    custom_prompt: Optional[str] = None
    temperature: Optional[float] = 0.1
    top_p: Optional[float] = 0.9
    max_tokens: Optional[int] = 1024
    repeat_penalty: Optional[float] = 1.1
    chat_history: Optional[List[Dict[str, Any]]] = None

class ChatReq(BaseModel):
    message: str
    backend: Optional[str] = None
    llm_source: Optional[str] = None
    model: Optional[str] = None
    top_k: int = 10
    system_prompt: Optional[str] = None
    chat_history: Optional[list] = None
    temperature: Optional[float] = 0.1
    top_p: Optional[float] = 0.9
    max_tokens: Optional[int] = 1024
    repeat_penalty: Optional[float] = 1.1
