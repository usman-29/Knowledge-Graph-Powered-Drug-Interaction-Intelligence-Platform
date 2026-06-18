/**
 * Edge-safe Auth.js config — no Node imports, no DB access.
 *
 * Used by middleware.ts which runs in the Edge runtime. The full config in
 * lib/auth.ts extends this with the credentials provider (which needs DB +
 * bcrypt — both Node-only).
 */
import type { NextAuthConfig } from "next-auth";

export const authConfig: NextAuthConfig = {
  trustHost: true,
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  providers: [],
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.id = user.id as string;
        token.role = (user as { role: "ADMIN" | "CLINICIAN" | "PATIENT" | "GUEST" }).role;
      }
      return token;
    },
    async session({ session, token }) {
      session.user.id = token.id as string;
      session.user.role = token.role as "ADMIN" | "CLINICIAN" | "PATIENT" | "GUEST";
      return session;
    },
  },
};
