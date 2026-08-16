import { Suspense } from "react";
import { Loader2 } from "lucide-react";
import InboxContent from "./inbox-client";

export default function InboxPage() {
  return (
    <Suspense fallback={<div className="flex justify-center py-12"><Loader2 size={16} className="animate-spin text-faint" /></div>}>
      <InboxContent />
    </Suspense>
  );
}
