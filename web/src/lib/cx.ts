/** Join class names, dropping anything falsy.
 *
 * Deliberately not `clsx`: this is the whole feature, and a dependency whose
 * source is shorter than its documentation is not worth installing.
 */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
