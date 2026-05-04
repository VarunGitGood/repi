import { InvestigationList } from "@/components/investigation-list"

export default function InvestigationsLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="flex h-[calc(100vh-3.5rem)] overflow-hidden">
      <InvestigationList />
      <div className="flex-1 overflow-auto bg-background">
        {children}
      </div>
    </div>
  )
}
