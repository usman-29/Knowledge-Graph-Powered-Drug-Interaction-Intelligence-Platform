"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Pill, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Medication } from "@/lib/backend";

type Props = {
  patientId: string;
  medications: Medication[];
};

export function MedicationEditor({ patientId, medications }: Props) {
  return (
    <div className="space-y-2">
      {medications.length === 0 ? (
        <p className="text-xs text-muted-foreground">No active medications.</p>
      ) : (
        medications.map((m) => (
          <MedicationRow key={m.name} patientId={patientId} medication={m} />
        ))
      )}
      <AddMedicationDialog patientId={patientId} />
    </div>
  );
}

function MedicationRow({
  patientId,
  medication,
}: {
  patientId: string;
  medication: Medication;
}) {
  const router = useRouter();
  const [removing, setRemoving] = useState(false);

  async function handleRemove() {
    if (removing) return;
    if (!confirm(`Remove ${medication.name} from this patient's medications?`)) return;
    setRemoving(true);
    try {
      const res = await fetch(
        `/api/patients/${encodeURIComponent(patientId)}/medications?name=${encodeURIComponent(medication.name)}`,
        { method: "DELETE" },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.details || body.error || `HTTP ${res.status}`);
      }
      toast.success(`Removed ${medication.name}`);
      router.refresh();
    } catch (err) {
      toast.error("Could not remove medication", { description: String(err) });
      setRemoving(false);
    }
  }

  return (
    <Card className="group p-3">
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-semibold">{medication.name}</span>
        <div className="flex items-center gap-1">
          <Badge variant="outline" className="shrink-0 text-[10px]">
            {medication.dose}
          </Badge>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-destructive"
            onClick={handleRemove}
            disabled={removing}
            aria-label={`Remove ${medication.name}`}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
      <div className="mt-1 text-xs text-muted-foreground">{medication.frequency}</div>
      <div className="mt-1 text-xs italic text-muted-foreground">{medication.indication}</div>
    </Card>
  );
}

function AddMedicationDialog({ patientId }: { patientId: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({
    name: "",
    dose: "",
    frequency: "",
    indication: "",
  });

  function reset() {
    setForm({ name: "", dose: "", frequency: "", indication: "" });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;

    const trimmed = {
      name: form.name.trim(),
      dose: form.dose.trim(),
      frequency: form.frequency.trim(),
      indication: form.indication.trim(),
    };

    if (!trimmed.name || !trimmed.dose || !trimmed.frequency || !trimmed.indication) {
      toast.error("Please fill in every field.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch(
        `/api/patients/${encodeURIComponent(patientId)}/medications`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(trimmed),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.details || body.error || `HTTP ${res.status}`);
      }
      toast.success(`Added ${trimmed.name} to the regimen`);
      reset();
      setOpen(false);
      router.refresh();
    } catch (err) {
      toast.error("Could not add medication", { description: String(err) });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => { setOpen(next); if (!next) reset(); }}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="w-full justify-start gap-2">
          <Plus className="h-3.5 w-3.5" />
          Add medication
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <Pill className="h-4 w-4" />
            Prescribe new medication
          </DialogTitle>
          <DialogDescription>
            Record a newly prescribed medication. It will be added to this patient&apos;s
            active regimen and included in future safety reviews.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="med-name">Medication name</Label>
              <Input
                id="med-name"
                placeholder="e.g. Atorvastatin"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                autoFocus
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="med-dose">Dose</Label>
              <Input
                id="med-dose"
                placeholder="e.g. 40 mg"
                value={form.dose}
                onChange={(e) => setForm({ ...form, dose: e.target.value })}
                required
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="med-frequency">Frequency</Label>
            <Input
              id="med-frequency"
              placeholder="e.g. once daily, twice daily, as needed"
              value={form.frequency}
              onChange={(e) => setForm({ ...form, frequency: e.target.value })}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="med-indication">Indication</Label>
            <Input
              id="med-indication"
              placeholder="e.g. Hyperlipidemia"
              value={form.indication}
              onChange={(e) => setForm({ ...form, indication: e.target.value })}
              required
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setOpen(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Saving…" : "Add to regimen"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
