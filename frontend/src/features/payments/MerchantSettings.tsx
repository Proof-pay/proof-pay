import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { type FormEvent, useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  errorMessage,
  getMerchantSettings,
  type MerchantSettings as Settings,
  saveMerchantSettings,
} from "./service"

export function MerchantSettings() {
  const query = useQuery({
    queryKey: ["merchant-settings"],
    queryFn: getMerchantSettings,
  })
  if (!query.data)
    return (
      <p role={query.error ? "alert" : "status"}>
        {query.error ? errorMessage(query.error) : "Loading merchant settings…"}
      </p>
    )
  return <SettingsForm key={query.dataUpdatedAt} initial={query.data} />
}
function SettingsForm({ initial }: { initial: Settings }) {
  const [values, setValues] = useState(initial)
  const cache = useQueryClient()
  const save = useMutation({
    mutationFn: saveMerchantSettings,
    onSuccess: () => {
      cache.invalidateQueries({ queryKey: ["merchant-settings"] })
      toast.success("Merchant settings saved")
    },
  })
  function submit(event: FormEvent) {
    event.preventDefault()
    const { network: _network, ...body } = values
    save.mutate({
      ...body,
      receiving_address: body.receiving_address || null,
      contact_email: body.contact_email || null,
      contact_phone: body.contact_phone || null,
    })
  }
  return (
    <form onSubmit={submit} className="max-w-xl space-y-5">
      <h2 className="font-semibold">Business and receiving wallet</h2>
      <p className="text-sm text-emerald-800">
        Deployment network: {initial.network}
      </p>
      <p className="text-sm text-slate-500">
        Use a wallet you control on this network. Every issued request needs its
        own fresh address. Settings changes apply to future requests.
      </p>
      {(
        [
          ["business_name", "Business name"],
          ["contact_email", "Contact email (private)"],
          ["contact_phone", "Contact phone (private)"],
          ["receiving_address", "Receiving wallet address"],
        ] as const
      ).map(([key, label]) => (
        <label
          className="block space-y-2 text-sm"
          key={key}
          htmlFor={`merchant-${key}`}
        >
          <span>{label}</span>
          <Input
            id={`merchant-${key}`}
            type={key === "contact_email" ? "email" : "text"}
            required={key === "business_name"}
            value={values[key] || ""}
            onChange={(e) => setValues({ ...values, [key]: e.target.value })}
          />
        </label>
      ))}
      <label className="block space-y-2 text-sm" htmlFor="merchant-expiry">
        <span>Default expiry (hours)</span>
        <Input
          id="merchant-expiry"
          type="number"
          min={1}
          max={2160}
          required
          value={values.default_expiry_hours}
          onChange={(e) =>
            setValues({
              ...values,
              default_expiry_hours: Number(e.target.value),
            })
          }
        />
      </label>
      <label
        className="block space-y-2 text-sm"
        htmlFor="merchant-confirmations"
      >
        <span>Required confirmations</span>
        <Input
          id="merchant-confirmations"
          type="number"
          min={1}
          max={100}
          required
          value={values.required_confirmations}
          onChange={(e) =>
            setValues({
              ...values,
              required_confirmations: Number(e.target.value),
            })
          }
        />
      </label>
      {save.error && (
        <p role="alert" className="text-sm text-red-700">
          {errorMessage(save.error)}
        </p>
      )}
      <Button type="submit" disabled={save.isPending}>
        {save.isPending ? "Saving…" : "Save merchant settings"}
      </Button>
    </form>
  )
}
