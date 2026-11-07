const PAGE_SIZE = 24;
const API_PATH = "/api/photos";
const CHECKOUT_PATH = "/api/checkout";

type PrintOption = {
  id: number | string;
  label: string;
  price: string;
};

type Photo = {
  thumbnail: string;
  lightbox: string;
  name: string;
  title: string;
  description: string;
  tags: string[];
  prints: PrintOption[];
  lastModified: string;
};

type GalleryState = {
  page: number;
  tag: string | null;
};

const statusEl = mustQuery<HTMLElement>("#status");
const gridEl = mustQuery<HTMLElement>("#grid");
const tagsEl = mustQuery<HTMLElement>("#tags");
const paginationEl = mustQuery<HTMLElement>("#pagination");
const lightbox = mustQuery<HTMLDialogElement>("#lightbox");
const lightboxImage = mustQuery<HTMLImageElement>("#lightbox img");
const lightboxTitle = mustQuery<HTMLElement>("#lightbox h2");
const lightboxDescription = mustQuery<HTMLElement>("#lightbox .description");
const lightboxTags = mustQuery<HTMLElement>("#lightbox .lightbox-tags");
const prevButton = mustQuery<HTMLButtonElement>("#lightbox .prev");
const nextButton = mustQuery<HTMLButtonElement>("#lightbox .next");
const buyForm = mustQuery<HTMLFormElement>("#buy");
const printSelect = mustQuery<HTMLSelectElement>("#print-variant");
const buyStatus = mustQuery<HTMLElement>(".buy-status");

let photos: Photo[] = [];
let pagePhotos: Photo[] = [];
let lightboxIndex = 0;

function mustQuery<T extends Element>(selector: string): T {
  const el = document.querySelector(selector);
  if (!el) {
    throw new Error(`Missing ${selector}`);
  }
  return el as T;
}

function readState(): GalleryState {
  const params = new URLSearchParams(window.location.search);
  const page = Number.parseInt(params.get("page") ?? "1", 10);
  const tag = params.get("tag");
  return {
    page: Number.isFinite(page) && page > 0 ? page : 1,
    tag: tag && tag.length > 0 ? tag : null,
  };
}

function writeState(state: GalleryState, push: boolean): void {
  const params = new URLSearchParams();
  if (state.tag) {
    params.set("tag", state.tag);
  }
  if (state.page > 1) {
    params.set("page", String(state.page));
  }
  const query = params.toString();
  const url = query ? `${window.location.pathname}?${query}` : window.location.pathname;
  if (push) {
    history.pushState(state, "", url);
  } else {
    history.replaceState(state, "", url);
  }
}

function uniqueTags(items: Photo[]): string[] {
  const found = new Set<string>();
  for (const photo of items) {
    for (const tag of photo.tags) {
      if (tag) {
        found.add(tag);
      }
    }
  }
  return [...found].sort((a, b) => a.localeCompare(b));
}

function filteredPhotos(tag: string | null): Photo[] {
  if (!tag) {
    return photos;
  }
  return photos.filter((photo) => photo.tags.includes(tag));
}

function pageCount(total: number): number {
  return Math.max(1, Math.ceil(total / PAGE_SIZE));
}

function setStatus(message: string | null): void {
  if (!message) {
    statusEl.hidden = true;
    statusEl.textContent = "";
    return;
  }
  statusEl.hidden = false;
  statusEl.textContent = message;
}

function renderTags(selected: string | null): void {
  const tags = uniqueTags(photos);
  tagsEl.replaceChildren();
  if (tags.length === 0) {
    tagsEl.hidden = true;
    return;
  }
  tagsEl.hidden = false;
  const all = document.createElement("button");
  all.type = "button";
  all.textContent = "All";
  if (!selected) {
    all.setAttribute("aria-current", "true");
  }
  all.addEventListener("click", () => applyState({ page: 1, tag: null }, true));
  tagsEl.append(all);
  for (const tag of tags) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = tag;
    if (tag === selected) {
      button.setAttribute("aria-current", "true");
    }
    button.addEventListener("click", () => applyState({ page: 1, tag }, true));
    tagsEl.append(button);
  }
}

function renderGrid(items: Photo[]): void {
  gridEl.replaceChildren();
  for (const [index, photo] of items.entries()) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tile";
    const image = document.createElement("img");
    image.src = photo.thumbnail;
    image.alt = photo.title;
    image.loading = "lazy";
    const caption = document.createElement("span");
    caption.textContent = photo.title;
    button.append(image, caption);
    button.addEventListener("click", () => openLightbox(index));
    gridEl.append(button);
  }
}

function renderPagination(page: number, pages: number): void {
  paginationEl.replaceChildren();
  if (pages <= 1) {
    paginationEl.hidden = true;
    return;
  }
  paginationEl.hidden = false;
  const previous = document.createElement("button");
  previous.type = "button";
  previous.textContent = "Previous";
  previous.disabled = page <= 1;
  previous.addEventListener("click", () => applyState({ ...readState(), page: page - 1 }, true));
  const label = document.createElement("span");
  label.textContent = `page ${page} of ${pages}`;
  const next = document.createElement("button");
  next.type = "button";
  next.textContent = "Next";
  next.disabled = page >= pages;
  next.addEventListener("click", () => applyState({ ...readState(), page: page + 1 }, true));
  paginationEl.append(previous, label, next);
}

function applyState(state: GalleryState, push: boolean): void {
  const matching = filteredPhotos(state.tag);
  const pages = pageCount(matching.length);
  const page = Math.min(Math.max(state.page, 1), pages);
  const nextState = { page, tag: state.tag };
  writeState(nextState, push);
  renderTags(nextState.tag);
  if (photos.length === 0) {
    pagePhotos = [];
    renderGrid([]);
    renderPagination(1, 1);
    setStatus("No photos yet.");
    return;
  }
  if (matching.length === 0) {
    pagePhotos = [];
    renderGrid([]);
    renderPagination(1, 1);
    setStatus("No photos with that tag.");
    return;
  }
  setStatus(null);
  const start = (page - 1) * PAGE_SIZE;
  pagePhotos = matching.slice(start, start + PAGE_SIZE);
  renderGrid(pagePhotos);
  renderPagination(page, pages);
  if (push) {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
}

function openLightbox(index: number): void {
  lightboxIndex = index;
  paintLightbox();
  if (!lightbox.open) {
    lightbox.showModal();
  }
}

function paintLightbox(): void {
  const photo = pagePhotos[lightboxIndex];
  if (!photo) {
    lightbox.close();
    return;
  }
  lightboxImage.src = photo.lightbox;
  lightboxImage.alt = photo.title;
  lightboxTitle.textContent = photo.title;
  lightboxDescription.textContent = photo.description;
  lightboxDescription.hidden = photo.description.length === 0;
  lightboxTags.replaceChildren();
  lightboxTags.hidden = photo.tags.length === 0;
  for (const tag of photo.tags) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = tag;
    button.addEventListener("click", () => {
      lightbox.close();
      applyState({ page: 1, tag }, true);
    });
    item.append(button);
    lightboxTags.append(item);
  }
  prevButton.disabled = lightboxIndex <= 0;
  nextButton.disabled = lightboxIndex >= pagePhotos.length - 1;
  paintBuy(photo);
}

function paintBuy(photo: Photo): void {
  printSelect.replaceChildren();
  buyStatus.hidden = true;
  buyStatus.textContent = "";
  if (photo.prints.length === 0) {
    buyForm.hidden = true;
    return;
  }
  buyForm.hidden = false;
  for (const option of photo.prints) {
    const item = document.createElement("option");
    item.value = String(option.id);
    item.textContent = option.price ? `${option.label} — $${option.price}` : option.label;
    printSelect.append(item);
  }
}

function setBuyStatus(message: string | null): void {
  if (!message) {
    buyStatus.hidden = true;
    buyStatus.textContent = "";
    return;
  }
  buyStatus.hidden = false;
  buyStatus.textContent = message;
}

async function startCheckout(event: SubmitEvent): Promise<void> {
  event.preventDefault();
  const photo = pagePhotos[lightboxIndex];
  if (!photo || printSelect.value === "") {
    return;
  }
  const button = buyForm.querySelector("button[type='submit']");
  if (button instanceof HTMLButtonElement) {
    button.disabled = true;
  }
  setBuyStatus("Opening checkout…");
  try {
    const response = await fetch(CHECKOUT_PATH, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ variant_id: Number.parseInt(printSelect.value, 10) }),
    });
    const payload: unknown = await response.json().catch(() => null);
    const error = errorMessage(payload);
    if (!response.ok) {
      setBuyStatus(error ?? "Checkout is not available yet.");
      return;
    }
    const url = checkoutUrl(payload);
    if (!url) {
      setBuyStatus("Checkout did not return a payment link.");
      return;
    }
    window.location.assign(url);
  } catch {
    setBuyStatus("Could not reach checkout.");
  } finally {
    if (button instanceof HTMLButtonElement) {
      button.disabled = false;
    }
  }
}

function errorMessage(payload: unknown): string | null {
  if (typeof payload !== "object" || payload === null || !("error" in payload)) {
    return null;
  }
  return typeof payload.error === "string" ? payload.error : null;
}

function checkoutUrl(payload: unknown): string | null {
  if (typeof payload !== "object" || payload === null || !("url" in payload)) {
    return null;
  }
  return typeof payload.url === "string" ? payload.url : null;
}

function checkoutNotice(): void {
  const params = new URLSearchParams(window.location.search);
  if (params.get("checkout") !== "success") {
    return;
  }
  params.delete("checkout");
  const query = params.toString();
  history.replaceState(
    readState(),
    "",
    query ? `${window.location.pathname}?${query}` : window.location.pathname,
  );
  setStatus("Thanks — your print is in production.");
}

function onKeydown(event: KeyboardEvent): void {
  if (!lightbox.open) {
    return;
  }
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    if (lightboxIndex > 0) {
      lightboxIndex -= 1;
      paintLightbox();
    }
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    if (lightboxIndex < pagePhotos.length - 1) {
      lightboxIndex += 1;
      paintLightbox();
    }
  }
}

async function loadPhotos(): Promise<void> {
  setStatus("Loading photographs.");
  const response = await fetch(API_PATH);
  if (!response.ok) {
    throw new Error(`Manifest failed: ${response.status}`);
  }
  const payload: unknown = await response.json();
  if (
    typeof payload !== "object" ||
    payload === null ||
    !("photos" in payload) ||
    !Array.isArray(payload.photos)
  ) {
    throw new Error("Manifest was not a photo list");
  }
  photos = payload.photos.filter(isPhoto).map((photo) => ({
    ...photo,
    prints: printsOf(photo).filter(isPrint),
  }));
}

function isPhoto(value: unknown): value is Photo {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const photo = value as Partial<Photo>;
  return (
    typeof photo.thumbnail === "string" &&
    typeof photo.lightbox === "string" &&
    typeof photo.name === "string" &&
    typeof photo.title === "string" &&
    typeof photo.description === "string" &&
    Array.isArray(photo.tags) &&
    photo.tags.every((tag) => typeof tag === "string") &&
    typeof photo.lastModified === "string"
  );
}

function printsOf(photo: Partial<Photo>): unknown[] {
  return Array.isArray(photo.prints) ? photo.prints : [];
}

function isPrint(value: unknown): value is PrintOption {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const option = value as Partial<PrintOption>;
  return (
    (typeof option.id === "number" || typeof option.id === "string") &&
    typeof option.label === "string" &&
    typeof option.price === "string"
  );
}

prevButton.addEventListener("click", () => {
  if (lightboxIndex > 0) {
    lightboxIndex -= 1;
    paintLightbox();
  }
});

nextButton.addEventListener("click", () => {
  if (lightboxIndex < pagePhotos.length - 1) {
    lightboxIndex += 1;
    paintLightbox();
  }
});

buyForm.addEventListener("submit", (event) => {
  void startCheckout(event);
});

lightbox.addEventListener("click", (event) => {
  if (event.target === lightbox) {
    lightbox.close();
  }
});

window.addEventListener("keydown", onKeydown);
window.addEventListener("popstate", () => applyState(readState(), false));

loadPhotos()
  .then(() => {
    applyState(readState(), false);
    checkoutNotice();
  })
  .catch(() => {
    photos = [];
    pagePhotos = [];
    renderGrid([]);
    renderPagination(1, 1);
    tagsEl.hidden = true;
    setStatus("Could not load photos.");
  });
