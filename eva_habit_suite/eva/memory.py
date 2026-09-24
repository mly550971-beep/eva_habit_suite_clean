"""Persistent conversation memory with Ollama embeddings and keyword fallback."""
from __future__ import annotations
import os, json, math, time, glob, uuid, threading
import requests
import secure_storage

class ConversationMemory:
    def __init__(self, client, config, logger):
        self.base_url = client.rstrip("/") if isinstance(client, str) else config.get("local_model", "base_url", default="http://127.0.0.1:11434").rstrip("/")
        self.logger = logger
        self.enabled = config.get("memory", "enabled", default=True)
        self.file_path = config.get("memory", "file", default="data/memory.json")
        self.embedding_model = config.get("model", "embedding_model", default="embeddinggemma")
        self.embedding_enabled = config.get("memory", "semantic_search", default=True)
        self.max_recent_turns = config.get("memory", "max_recent_turns", default=12)
        self.semantic_top_k = config.get("memory", "semantic_top_k", default=3)
        self.min_similarity = config.get("memory", "semantic_min_similarity", default=0.45)
        self.sessions_dir = config.get("memory", "sessions_dir", default="data/sessions")
        self.embed_timeout = int(config.get("local_model", "embedding_timeout", default=60))
        self.turns = []
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if not self.enabled: return
        try:
            self.turns = secure_storage.load_json(self.file_path, self.logger, default=[]) or []
            self.logger.info(f"Loaded {len(self.turns)} messages from persistent memory.")
        except Exception as e:
            self.logger.warning(f"Could not load memory file, starting with empty memory: {e}")
            self.turns = []

    def _save(self):
        if not self.enabled: return
        try: secure_storage.save_json(self.file_path, self.turns, self.logger)
        except Exception as e: self.logger.warning(f"Could not save memory to disk: {e}")

    def _embed(self, text: str):
        if not self.embedding_enabled or not self.embedding_model: return None
        try:
            r = requests.post(f"{self.base_url}/api/embed", json={"model": self.embedding_model, "input": text}, timeout=self.embed_timeout)
            r.raise_for_status()
            data = r.json()
            embs = data.get("embeddings") or []
            return list(embs[0]) if embs else None
        except Exception as e:
            self.logger.debug(f"Could not generate local embedding: {e}")
            return None

    @staticmethod
    def _cosine_similarity(a,b):
        if not a or not b or len(a)!=len(b): return 0.0
        dot=sum(x*y for x,y in zip(a,b)); na=math.sqrt(sum(x*x for x in a)); nb=math.sqrt(sum(y*y for y in b))
        return 0.0 if not na or not nb else dot/(na*nb)

    @staticmethod
    def _keyword_score(query, text):
        q={x for x in query.lower().split() if len(x)>2}; t=set(text.lower().split())
        return len(q & t)/max(1,len(q))

    def add_exchange(self, user_text, model_text):
        if not self.enabled: return
        user_turn={"role":"user","text":user_text,"embedding":None,"ts":time.time()}
        model_turn={"role":"model","text":model_text,"embedding":None,"ts":time.time()}
        with self._lock:
            self.turns.extend([user_turn, model_turn]); self._save()
        def worker():
            emb=self._embed(user_text)
            if emb is not None:
                with self._lock:
                    user_turn["embedding"]=emb; self._save()
        threading.Thread(target=worker, daemon=True).start()

    def get_context(self, query_text):
        if not self.enabled or not self.turns: return ""
        with self._lock: snapshot=list(self.turns)
        recent=snapshot[-self.max_recent_turns:]; recent_ids={id(t) for t in recent}
        candidates=[t for t in snapshot if id(t) not in recent_ids]
        relevant=[]
        qemb=self._embed(query_text) if self.embedding_enabled else None
        if qemb:
            scored=[(self._cosine_similarity(qemb,t.get("embedding"),),t) for t in candidates if t.get("embedding")]
            scored.sort(key=lambda x:x[0], reverse=True)
            relevant=[t for score,t in scored[:self.semantic_top_k] if score>=self.min_similarity]
        if not relevant and candidates:
            scored=sorted(((self._keyword_score(query_text,t.get("text","")),t) for t in candidates), key=lambda x:x[0], reverse=True)
            relevant=[t for score,t in scored[:self.semantic_top_k] if score>0]
        lines=[]
        if relevant:
            lines.append("Relevant older memories:")
            lines += [f"- {'User' if t['role']=='user' else 'Eva'}: {t['text']}" for t in relevant]
        lines.append("Recent conversation:")
        lines += [f"{'User' if t['role']=='user' else 'Eva'}: {t['text']}" for t in recent]
        return "\n".join(lines)

    def clear(self):
        self._archive_current_session()
        with self._lock:
            self.turns=[]
            if self.enabled and os.path.exists(self.file_path):
                try: os.remove(self.file_path)
                except Exception as e: self.logger.warning(f"Could not delete memory file: {e}")

    def _archive_current_session(self):
        if not self.enabled or not self.turns: return
        try:
            with self._lock: snapshot=list(self.turns)
            os.makedirs(self.sessions_dir, exist_ok=True)
            first_user=next((t for t in snapshot if t.get("role")=="user"),None)
            session={"id":str(uuid.uuid4()),"ts":time.time(),"preview":(first_user["text"][:60] if first_user else "Conversation"),"turns":[{"role":t["role"],"text":t["text"],"ts":t.get("ts")} for t in snapshot]}
            with open(os.path.join(self.sessions_dir,f"{int(session['ts'])}_{session['id'][:8]}.json"),"w",encoding="utf-8") as f: json.dump(session,f,ensure_ascii=False,indent=2)
        except Exception as e: self.logger.warning(f"Could not archive conversation to history: {e}")

    def list_sessions(self):
        results=[]
        if not os.path.isdir(self.sessions_dir): return results
        for path in glob.glob(os.path.join(self.sessions_dir,"*.json")):
            try:
                with open(path,encoding="utf-8") as f: data=json.load(f)
                results.append({"id":data.get("id"),"ts":data.get("ts",0),"preview":data.get("preview",""),"path":path})
            except Exception: pass
        results.sort(key=lambda s:s["ts"], reverse=True); return results

    def load_session(self,path):
        try:
            with open(path,encoding="utf-8") as f: return json.load(f).get("turns",[])
        except Exception as e:
            self.logger.warning(f"Could not load archived session: {e}"); return []
