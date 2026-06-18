/**
 * Edge-runtime route protection.
 *
 * Uses lib/auth.config.ts (no DB, no Node imports) — DO NOT import lib/auth.ts
 * here; it pulls in better-sqlite3 which will crash the Edge bundle.
 */
import NextAuth from "next-auth";
import { NextResponse } from "next/server";
import { authConfig } from "@/lib/auth.config";

const { auth } = NextAuth(authConfig);

export default auth((req) => {
  const { pathname } = req.nextUrl;
  const isAuthed = !!req.auth;
  const isAdmin = req.auth?.user?.role === "ADMIN";

  const publicPaths = ["/login", "/register"];
  const isPublic = publicPaths.some((p) => pathname.startsWith(p));

  if (!isAuthed && !isPublic) {
    return NextResponse.redirect(new URL("/login", req.nextUrl));
  }
  if (isAuthed && isPublic) {
    return NextResponse.redirect(new URL("/chat", req.nextUrl));
  }
  if (pathname.startsWith("/admin") && !isAdmin) {
    return NextResponse.redirect(new URL("/chat", req.nextUrl));
  }
  return NextResponse.next();
});

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\..*).*)"],
};
