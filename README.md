# opt-rag

一個最小可運作的 RAG 服務：文件進 Supabase pgvector，查詢時檢索相關片段交給 Gemini 生成答案。

要證明的是：我能設計一個可評測的 RAG pipeline，並用 eval 數字說明每一個設計決策——為什麼這樣切 chunk、為什麼選這個 top-k、為什麼換掉那個 prompt。

技術棧：Python 3.12、FastAPI、uv、Gemini API、Supabase (pgvector)。

目前狀態：環境骨架，只有 `GET /health`。
