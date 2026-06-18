/**
 * POST /api/chat — authenticated proxy to the FastAPI backend's /chat endpoint.
 *
 * The user_id we forward is the SQLite row id, which we mirrored to the backend
 * RBAC registry at register-time. The backend re-derives the user's role.
 *
 * If `patient_id` is supplied, the backend prepends that patient's clinical
 * context (current meds, allergies, conditions) before reasoning.
 */
import { NextResponse } from "next/server";
import { z } from "zod";

import { auth } from "@/lib/auth";
import { backend } from "@/lib/backend";

const Body = z.object({
  query: z.string().min(1).max(4000),
  thread_id: z.string().optional(),
  patient_id: z.string().optional(),
});

export async function POST(req: Request) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  let parsed;
  try {
    parsed = Body.parse(await req.json());
  } catch (err) {
    return NextResponse.json({ error: "Invalid input", details: String(err) }, { status: 400 });
  }

  try {
    const data = await backend.chat({
      query: parsed.query,
      user_id: session.user.id,
      thread_id: parsed.thread_id,
      patient_id: parsed.patient_id,
    });
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json(
      { error: "Backend request failed", details: String(err) },
      { status: 502 },
    );
  }
}
