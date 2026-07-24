export interface EquipmentImageMetadata {
  src: string;
  alt: string;
  naturalWidth: number;
  naturalHeight: number;
  source: "fixture" | "uploaded";
}

const showcaseReference: EquipmentImageMetadata = {
  src: "/refrigeration/showcase-reference.svg",
  alt: "Фронтальний вигляд холодильної вітрини з чотирма полицями",
  naturalWidth: 1600,
  naturalHeight: 1000,
  source: "fixture",
};

const equipmentImages: Record<string, EquipmentImageMetadata> = {
  "showcase-106-01": showcaseReference,
  "showcase-107-02": {
    ...showcaseReference,
    alt: "Фронтальний вигляд компактної холодильної вітрини",
  },
  "cold-room-201": {
    ...showcaseReference,
    alt: "Референсне зображення холодильної камери",
  },
};

export function getEquipmentImage(equipmentId: string): EquipmentImageMetadata {
  return equipmentImages[equipmentId] ?? showcaseReference;
}
