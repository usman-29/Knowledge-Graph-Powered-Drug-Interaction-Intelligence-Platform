/**
 * POST /api/register — thin proxy to the FastAPI backend's /auth/register.
 *
 * The frontend has no database. The backend is the source of truth for all
 * user state (email, password hash, role).
 */
import { NextResponse } from "next/server";
import { z } from "zod";

import { backend } from "@/lib/backend";

const Body = z.object({
  email: z.string().email().toLowerCase(),
  name: z.string().min(1).max(80),
  password: z.string().min(8).max(128),
  role: z.enum(["ADMIN", "CLINICIAN", "PATIENT"]),
});

export async function POST(req: Request) {
  let parsed;
  try {
    parsed = Body.parse(await req.json());
  } catch (err) {
    return NextResponse.json({ error: "Invalid input", details: String(err) }, { status: 400 });
  }

  try {
    const user = await backend.registerUser(parsed);
    return NextResponse.json(user, { status: 201 });
  } catch (err) {
    const message = String(err);
    if (message.includes("409")) {
      return NextResponse.json({ error: "An account with that email already exists." }, { status: 409 });
    }
    return NextResponse.json({ error: "Registration failed", details: message }, { status: 502 });
  }
}
