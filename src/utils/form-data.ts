export function createFormData(obj: object) {
  const formData = new FormData()
  for (const [key, value] of Object.entries(obj)) {
    formData.append(key, value)
  }

  return formData
}
