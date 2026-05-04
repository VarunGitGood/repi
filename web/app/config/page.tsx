import { ConfigForm } from "@/components/config-form"
import { WatcherForm } from "@/components/watcher-form"
import { Separator } from "@/components/ui/separator"

export default function ConfigPage() {
  return (
    <div className="container max-w-7xl mx-auto py-10 px-4">
      <div className="space-y-0.5">
        <h2 className="text-2xl font-bold tracking-tight">Configuration</h2>
        <p className="text-muted-foreground">
          Manage your application settings and log watchers.
        </p>
      </div>
      <Separator className="my-6" />
      <div className="flex flex-col space-y-8 lg:flex-row lg:space-x-12 lg:space-y-0">
        <div className="flex-1">
          <section className="space-y-6">
            <div>
              <h3 className="text-lg font-medium">Application Settings</h3>
              <p className="text-sm text-muted-foreground">
                Core configuration for database, LLM, and investigation parameters.
              </p>
            </div>
            <ConfigForm />
          </section>
          
          <Separator className="my-10" />
          
          <section className="space-y-6">
            <div>
              <h3 className="text-lg font-medium">Log Watchers</h3>
              <p className="text-sm text-muted-foreground">
                Define the log files that repi should monitor and ingest.
              </p>
            </div>
            <WatcherForm />
          </section>
        </div>
      </div>
    </div>
  )
}
