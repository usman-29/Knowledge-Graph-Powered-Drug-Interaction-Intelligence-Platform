"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { signIn } from "next-auth/react";
import { toast } from "sonner";
import { Stethoscope, User, ShieldCheck, Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

const ROLES = [
  {
    value: "CLINICIAN",
    label: "Clinician",
    description: "Query drug interactions and FDA warnings",
    icon: Stethoscope,
  },
  {
    value: "PATIENT",
    label: "Patient",
    description: "Read-only access for self-care queries",
    icon: User,
  },
  {
    value: "ADMIN",
    label: "Administrator",
    description: "Full access including audit dashboard",
    icon: ShieldCheck,
  },
] as const;

type RoleValue = (typeof ROLES)[number]["value"];

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<RoleValue>("CLINICIAN");
  const [pending, setPending] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    try {
      const res = await fetch("/api/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, password, role }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        toast.error("Registration failed", { description: data.error || `HTTP ${res.status}` });
        setPending(false);
        return;
      }
      const signin = await signIn("credentials", { email, password, redirect: false });
      if (signin?.error) {
        toast.error("Auto sign-in failed", { description: "Please log in manually." });
        router.push("/login");
        return;
      }
      router.push("/chat");
      router.refresh();
    } finally {
      setPending(false);
    }
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle className="text-base">Create an account</CardTitle>
        <CardDescription>Register to use the drug-safety assistant.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="name">Full Name</Label>
            <Input id="name" required value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              minLength={8}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">At least 8 characters.</p>
          </div>

          <div className="space-y-2">
            <Label>Role</Label>
            <div className="grid grid-cols-3 gap-2">
              {ROLES.map((r) => {
                const Icon = r.icon;
                const selected = role === r.value;
                return (
                  <button
                    key={r.value}
                    type="button"
                    onClick={() => setRole(r.value)}
                    className={cn(
                      "relative flex flex-col items-center gap-2 rounded-lg border p-3 text-center transition-all",
                      "hover:bg-accent hover:border-ring/40",
                      selected
                        ? "border-ring bg-accent shadow-sm"
                        : "border-border bg-transparent"
                    )}
                  >
                    {selected && (
                      <span className="absolute right-1.5 top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-foreground">
                        <Check className="h-2.5 w-2.5 text-background" />
                      </span>
                    )}
                    <Icon className={cn("h-5 w-5", selected ? "text-foreground" : "text-muted-foreground")} />
                    <div>
                      <div className={cn("text-xs font-semibold", selected ? "text-foreground" : "text-muted-foreground")}>
                        {r.label}
                      </div>
                      <div className="mt-0.5 text-[10px] leading-snug text-muted-foreground">
                        {r.description}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <Button type="submit" className="w-full" disabled={pending}>
            {pending ? "Creating account…" : "Create Account"}
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            Already have an account?{" "}
            <Link href="/login" className="underline underline-offset-4">
              Sign in
            </Link>
          </p>
        </form>
      </CardContent>
    </Card>
  );
}
