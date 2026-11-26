// Crawlers are asked not to index anything. This is not access control: every private
// route still requires authentication.
export const dynamic = "force-static";

export function GET() {
  return new Response("User-agent: *\nDisallow: /\n", {
    headers: { "content-type": "text/plain", "x-robots-tag": "noindex, nofollow, noarchive, nosnippet" },
  });
}
