import { forward } from "@/lib/upstream";

export const dynamic = "force-dynamic";

// Public report pages are rendered by the API (shared template with the PDF renderer).
async function handle(request: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return forward(request, `/r/${path.map(encodeURIComponent).join("/")}`);
}

export { handle as GET, handle as POST };
