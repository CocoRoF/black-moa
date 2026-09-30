/** Embedding models we know the shape of, so the admin picks a name instead of typing one.
 *
 *  A wrong dimension is not a validation error the user sees — it is a reindex that produces
 *  vectors the database rejects, hours later. `dims` lists the sizes a model can be asked
 *  for; the first is its native size.
 */
export interface EmbeddingModel {
  id: string;
  dims: number[];
  note?: string;
}

export const EMBEDDING_PROVIDERS = [
  { value: "openai", label: "OpenAI" },
  { value: "voyage", label: "Voyage AI" },
  { value: "google", label: "Google (Gemini)" },
] as const;

export const EMBEDDING_MODELS: Record<string, EmbeddingModel[]> = {
  openai: [
    { id: "text-embedding-3-small", dims: [1536, 512] },
    { id: "text-embedding-3-large", dims: [3072, 1024, 256] },
    { id: "text-embedding-ada-002", dims: [1536] },
  ],
  voyage: [
    { id: "voyage-3-large", dims: [1024, 2048, 512, 256] },
    { id: "voyage-3", dims: [1024] },
    { id: "voyage-3-lite", dims: [512] },
    { id: "voyage-multilingual-2", dims: [1024] },
    { id: "voyage-code-3", dims: [1024, 2048, 512, 256] },
  ],
  google: [
    { id: "gemini-embedding-001", dims: [3072, 1536, 768] },
    { id: "text-embedding-004", dims: [768] },
    { id: "text-multilingual-embedding-002", dims: [768] },
  ],
};

export const CUSTOM_MODEL = "__custom__";

export function findModel(provider: string, id: string): EmbeddingModel | undefined {
  return (EMBEDDING_MODELS[provider] ?? []).find((m) => m.id === id);
}
