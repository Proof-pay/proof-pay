import DeleteConfirmation from "./DeleteConfirmation"

const DeleteAccount = () => {
  return (
    <div className="max-w-md rounded-xl border border-destructive/30 bg-red-50/40 p-5">
      <h3 className="font-semibold text-destructive">Delete Account</h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Permanently delete your account and all associated data.
      </p>
      <DeleteConfirmation />
    </div>
  )
}

export default DeleteAccount
