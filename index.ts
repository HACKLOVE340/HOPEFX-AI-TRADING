/**
 * Vercel AI Gateway example — HOPEFX
 * ==================================
 *
 * Standalone on purpose. This is NOT part of `frontend/`: `generateText` is a
 * server-side call and `AI_GATEWAY_API_KEY` would be bundled into the Vite SPA
 * and served to every visitor if it were imported from client code.
 *
 * Run:
 *     npm run example
 *
 * which is `node --env-file=.env.local index.ts` — Node 22 loads the env file
 * and strips the types, so there is no dotenv or ts-node dependency.
 *
 * The key is read from the environment by the AI SDK itself; it is never
 * printed, logged, or passed through argv here.
 */

import { generateText } from "ai";

async function main(): Promise<void> {
  if (!process.env.AI_GATEWAY_API_KEY) {
    // Fail closed and say which file to edit, rather than letting the SDK
    // return an opaque 401 from the gateway.
    console.error(
      "AI_GATEWAY_API_KEY is empty.\n" +
        "Add your key to .env.local (gitignored) and re-run `npm run example`.",
    );
    process.exitCode = 1;
    return;
  }

  const { text } = await generateText({
    model: "openai/gpt-5.5",
    prompt: "Invent a new holiday and describe its traditions.",
  });

  console.log(text);
}

main().catch((error: unknown) => {
  console.error("generateText failed:", error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
