import os
import re
import json
import hashlib
from urllib.parse import urlparse

import chromadb
from chromadb.utils import embedding_functions
from pypdf import PdfReader
from google import genai
from tavily import TavilyClient


class ResearchAssistant:
    """Session-scoped PDF RAG with optional live web evidence."""

    def __init__(self, gemini_api_key, tavily_api_key=None):
        self.client = genai.Client(api_key=gemini_api_key)
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.tavily_api_key = tavily_api_key
        self.chroma_client = chromadb.Client()
        self.collection = None
        self.document_name = "uploaded.pdf"

    def _generate(self, prompt):
        response = self.client.models.generate_content(model=self.model, contents=prompt)
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("The Gemini model returned an empty response.")
        return text.strip()

    @staticmethod
    def _parse_json(text):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.S)
            if match:
                return json.loads(match.group(0))
            raise RuntimeError("Could not parse the model's routing response.")

    
    def index_pdf(self, pdf_path, original_name):
        self.document_name = original_name
        reader = PdfReader(pdf_path)

        documents, metadatas, ids = [], [], []
        chunk_size, overlap = 1100, 180
        total_extracted_chars = 0

        for page_num, page in enumerate(reader.pages, start=1):
            raw_text = page.extract_text() or ""
            total_extracted_chars += len(raw_text)

            text = re.sub(r"\s+", " ", raw_text).strip()
            start = 0

            while start < len(text):
                chunk = text[start:start + chunk_size].strip()

                if len(chunk) > 50:
                    documents.append(chunk)
                    metadatas.append({
                        "page": page_num,
                        "filename": original_name
                    })
                    chunk_id = hashlib.sha256(
                        f"{page_num}:{start}:{chunk[:80]}".encode()
                    ).hexdigest()[:24]
                    ids.append(chunk_id)

                if start + chunk_size >= len(text):
                    break

                start += chunk_size - overlap

        if not documents:
            raise RuntimeError(
                f"PDF text extraction returned no usable chunks. "
                f"Pages: {len(reader.pages)}; "
                f"characters extracted: {total_extracted_chars}. "
                f"If characters are zero, the PDF may be scanned "
                f"and require OCR. If characters exist but are too short, "
                f"the PDF may contain very little readable text."
            )

        ef = embedding_functions.DefaultEmbeddingFunction()

        collection_name = "paper_" + hashlib.md5(
            (original_name + str(len(documents))).encode()
        ).hexdigest()[:12]

        try:
            self.chroma_client.delete_collection(collection_name)
        except Exception:
            pass

        self.collection = self.chroma_client.create_collection(
            name=collection_name,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"}
        )

        self.collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )

    def retrieve_pdf(self, question, k=5):
        if not self.collection:
            return []
        result = self.collection.query(query_texts=[question], n_results=min(k, self.collection.count()))
        evidence = []
        for text, metadata, distance in zip(
            result["documents"][0], result["metadatas"][0], result.get("distances", [[]])[0]
        ):
            evidence.append({"text": text, "page": metadata.get("page", "?"), "distance": distance})
        return evidence

    def _route_question(self, question, allow_web):
        prompt = f"""Decide what evidence is needed to answer the user's question.
Return ONLY JSON with keys route and reason.
route must be one of: "document_only", "web_only", "both".
Use document_only for questions answerable from the uploaded paper.
Use web_only for questions primarily about current facts unrelated to the paper.
Use both for comparisons, recent developments related to the paper, or questions needing paper context plus external evidence.
If web search is disabled, choose document_only.
Question: {question}
Web search enabled: {allow_web}"""
        try:
            data = self._parse_json(self._generate(prompt))
            route = data.get("route", "both")
            if route not in {"document_only", "web_only", "both"}:
                route = "both"
            if not allow_web:
                route = "document_only"
            return route, str(data.get("reason", "Evidence route selected based on the question."))
        except Exception:
            return ("both" if allow_web else "document_only"), "Fallback routing was used because the routing response could not be parsed."

    def _search_web(self, question):
        if not self.tavily_api_key:
            return []
        client = TavilyClient(api_key=self.tavily_api_key)
        try:
            result = client.search(query=question, search_depth="basic", max_results=5, include_answer=False)
        except Exception as exc:
            raise RuntimeError(f"Web search failed: {exc}") from exc
        sources, seen = [], set()
        for item in result.get("results", []):
            url = item.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            sources.append({
                "title": item.get("title") or url,
                "url": url,
                "domain": urlparse(url).netloc.replace("www.", ""),
                "snippet": item.get("content", "") or ""
            })
        return sources

    def answer(self, question, allow_web=True, detail="Standard"):
        route, reason = self._route_question(question, allow_web)
        document_evidence = []
        web_sources = []
        if route in {"document_only", "both"}:
            document_evidence = self.retrieve_pdf(question, k=4 if detail == "Brief" else 6)
        if route in {"web_only", "both"} and allow_web:
            web_sources = self._search_web(question)

        evidence_blocks = []
        for i, item in enumerate(document_evidence, 1):
            evidence_blocks.append(f"[PDF p.{item['page']}] {item['text']}")
        for i, item in enumerate(web_sources, 1):
            evidence_blocks.append(f"[W{i}] {item['title']} — {item['url']}\nSnippet: {item['snippet']}")
        if not evidence_blocks:
            raise RuntimeError("No evidence was retrieved. Try a different question or enable web search.")

        length = {"Brief": "about 250 words", "Standard": "about 500 words", "Detailed": "about 800 words"}.get(detail, "about 500 words")
        prompt = f"""You are PaperPilot, an evidence-grounded research assistant. Answer in {length}.
Question: {question}
Uploaded PDF: {self.document_name}

Use the evidence below. Distinguish uploaded-paper evidence from web evidence.
Cite PDF claims as (PDF, p. N) when a page is supplied. Cite web results using [W1], [W2], etc.
Only use web citation IDs that exist in the supplied evidence. Do not invent facts, sources, URLs, quotes, or publication dates.
If the evidence is insufficient or conflicting, say so. Do not claim independent fact-checking.
Format the answer with a direct answer, explanation, comparison where relevant, limitations, and sources used.

EVIDENCE:
{chr(10).join(evidence_blocks)}
"""
        answer = self._generate(prompt)
        return {
            "answer": answer,
            "route": route,
            "reason": reason,
            "document_evidence": document_evidence,
            "web_sources": web_sources
        }
