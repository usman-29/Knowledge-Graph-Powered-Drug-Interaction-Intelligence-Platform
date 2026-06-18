/**
 * Medication management for a single patient — authenticated proxy to FastAPI.
 *
 *   POST   /api/patients/:id/medications        — add a new medication
 *   DELETE /api/patients/:id/medications?name=…  — remove a medication by name
 *
 * Both routes are gated by the standard session check. The backend handles
 * idempotency and persistence (writes to data/patients.json).
 */
import { NextResponse } from "next/server";
import { z } from "zod";

import { auth } from "@/lib/auth";
import { backend } from "@/lib/backend";

const MedicationBody = z.object({
  name: z.string().trim().min(1).max(120),
  dose: z.string().trim().min(1).max(60),
  frequency: z.string().trim().min(1).max(60),
  indication: z.string().trim().min(1).max(200),
});

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { id } = await params;

  let parsed;
  try {
    parsed = MedicationBody.parse(await req.json());
  } catch (err) {
    return NextResponse.json(
      { error: "Invalid medication", details: String(err) },
      { status: 400 },
    );
  }

  try {
    const updated = await backend.addMedication(id, parsed);
    return NextResponse.json(updated);
  } catch (err) {
    return NextResponse.json(
      { error: "Backend request failed", details: String(err) },
      { status: 502 },
    );
  }
}

export async function DELETE(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { id } = await params;
  const url = new URL(req.url);
  const name = url.searchParams.get("name");
  if (!name) {
    return NextResponse.json(
      { error: "Missing 'name' query parameter" },
      { status: 400 },
    );
  }

  try {
    const updated = await backend.removeMedication(id, name);
    return NextResponse.json(updated);
  } catch (err) {
    return NextResponse.json(
      { error: "Backend request failed", details: String(err) },
      { status: 502 },
    );
  }
}
