import { auth } from "@/lib/auth";
import { ChatInterface } from "@/components/chat/chat-interface";

export default async function ChatPage() {
  const session = await auth();
  const name = session?.user.name || session?.user.email || "You";
  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 items-center border-b px-6">
        <div>
          <h1 className="text-sm font-semibold">Drug-Safety Assistant</h1>
          <p className="text-xs text-muted-foreground">
            Every query passes through the three-tier security stack.
          </p>
        </div>
      </header>
      <div className="flex-1 overflow-hidden">
        <ChatInterface userName={name} />
      </div>
    </div>
  );
}
