// Evento global: «los datos de horas/viajes cambiaron en el servidor».
// Lo disparan el Inicio y el prompt de cierre olvidado; se suscriben las
// pantallas que muestran esos datos (Inicio, Horas, Planificador).

const EVENT = "work-data-changed";

export function notifyWorkDataChanged(): void {
  window.dispatchEvent(new Event(EVENT));
}

/** Suscribe un callback; devuelve la función de baja. */
export function onWorkDataChanged(cb: () => void): () => void {
  window.addEventListener(EVENT, cb);
  return () => window.removeEventListener(EVENT, cb);
}
