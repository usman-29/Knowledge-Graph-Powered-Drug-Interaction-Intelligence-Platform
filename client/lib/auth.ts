/**
 * Auth.js v5 — credentials provider that delegates to the FastAPI backend.
 *
 * The frontend has no database. Username/password verification is performed
 * by POSTing to the backend's /auth/verify endpoint. The returned user info
 * (id + role) is then stamped onto a JWT session cookie.
 */
import NextAuth, { type DefaultSession } from "next-auth";
import Credentials from "next-auth/providers/credentials";

import { authConfig } from "@/lib/auth.config";
import { backend } from "@/lib/backend";

declare module "next-auth" {
  interface Session {
    user: { id: string; role: "ADMIN" | "CLINICIAN" | "PATIENT" | "GUEST" } & DefaultSession["user"];
  }
  interface User {
    role: "ADMIN" | "CLINICIAN" | "PATIENT" | "GUEST";
  }
}

declare module "@auth/core/jwt" {
  interface JWT {
    id: string;
    role: "ADMIN" | "CLINICIAN" | "PATIENT" | "GUEST";
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  ...authConfig,
  providers: [
    Credentials({
      credentials: { email: {}, password: {} },
      async authorize(credentials) {
        const email = String(credentials?.email || "").toLowerCase().trim();
        const password = String(credentials?.password || "");
        if (!email || !password) return null;

        try {
          const user = await backend.verifyUser({ email, password });
          if (!user) return null;
          return { id: user.id, email: user.email, name: user.name || user.email, role: user.role };
        } catch (err) {
          console.error("Auth verify failed:", err);
          return null;
        }
      },
    }),
  ],
});
