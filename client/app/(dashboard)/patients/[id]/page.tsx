import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, AlertTriangle, Pill, Activity } from "lucide-react";

import { ChatInterface } from "@/components/chat/chat-interface";
import { MedicationEditor } from "@/components/patients/medication-editor";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { auth } from "@/lib/auth";
import { backend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function PatientDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const session = await auth();
  const userName = session?.user.name || session?.user.email || "You";

  let patient;
  try {
    patient = await backend.getPatient(id);
  } catch {
    notFound();
  }

  return (
    <div className="flex h-full">
      <PatientPanel patient={patient} />
      <div className="flex-1 border-l">
        <ChatInterface userName={userName} patient={patient} />
      </div>
    </div>
  );
}

type PatientType = NonNullable<Awaited<ReturnType<typeof backend.getPatient>>>;

function PatientPanel({ patient }: { patient: PatientType }) {
  return (
    <aside className="flex w-80 flex-col border-r">
      {/* Header */}
      <header className="flex h-14 items-center gap-2 border-b px-4">
        <Link href="/patients" className="text-muted-foreground hover:text-foreground transition-colors">
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <span className="text-sm font-semibold">{patient.display_name}</span>
        <Badge variant="outline" className="ml-auto font-mono text-[10px]">
          {patient.id}
        </Badge>
      </header>

      <div className="flex-1 overflow-y-auto">
        {/* Demographics card */}
        <div className="p-4 pb-0">
          <Card className="p-4">
            <div className="grid grid-cols-2 gap-3 text-xs">
              <Stat label="Age" value={String(patient.age)} />
              <Stat label="Sex" value={patient.sex} />
              <Stat label="Conditions" value={String(patient.conditions.length)} />
              <Stat label="Medications" value={String(patient.medications.length)} />
            </div>
          </Card>
        </div>

        <div className="space-y-0 p-4">
          {/* Conditions */}
          <Section title="Active Conditions" icon={<Activity className="h-3.5 w-3.5" />}>
            {patient.conditions.length === 0 ? (
              <EmptyState />
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {patient.conditions.map((c) => (
                  <Badge key={c} variant="secondary" className="font-normal text-xs">
                    {c}
                  </Badge>
                ))}
              </div>
            )}
          </Section>

          <Separator className="my-4" />

          {/* Allergies */}
          <Section
            title="Known Allergies"
            icon={<AlertTriangle className="h-3.5 w-3.5 text-destructive" />}
          >
            {patient.allergies.length === 0 ? (
              <p className="text-xs text-muted-foreground">No known allergies recorded.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {patient.allergies.map((a) => (
                  <Badge key={a} variant="destructive" className="font-normal text-xs">
                    {a}
                  </Badge>
                ))}
              </div>
            )}
          </Section>

          <Separator className="my-4" />

          {/* Medications */}
          <Section
            title={`Current Medications (${patient.medications.length})`}
            icon={<Pill className="h-3.5 w-3.5" />}
          >
            <MedicationEditor
              patientId={patient.id}
              medications={patient.medications}
            />
          </Section>
        </div>
      </div>
    </aside>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-sm font-semibold">{value}</div>
    </div>
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="mb-2.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {icon}
        {title}
      </div>
      {children}
    </section>
  );
}

function EmptyState({ text = "—" }: { text?: string }) {
  return <p className="text-xs text-muted-foreground">{text}</p>;
}
