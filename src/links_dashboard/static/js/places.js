export const NO_GROUP_LABEL = "Без группы";
const SEPARATOR = "\u0000";

export function placeOf(group, subgroup) {
  return Object.freeze({ group: group || "", subgroup: group ? subgroup || null : null });
}

export function placeId(place) {
  return `${place.group}${SEPARATOR}${place.subgroup || ""}`;
}

export function placeFromId(id) {
  const [group, subgroup] = id.split(SEPARATOR);
  return placeOf(group, subgroup);
}

export function samePlace(a, b) {
  return Boolean(a && b) && placeId(a) === placeId(b);
}

export function placeLabel(place) {
  if (!place.group) return NO_GROUP_LABEL;
  return place.subgroup ? `${place.group} / ${place.subgroup}` : place.group;
}

export function noteScope(place) {
  return place.subgroup ? `${place.group}/${place.subgroup}` : place.group;
}

export function groupedTree(nodes) {
  const order = [];
  const byGroup = new Map();
  for (const node of nodes) {
    if (!byGroup.has(node.group)) {
      order.push(node.group);
      byGroup.set(node.group, { group: node.group, own: null, subgroups: [] });
    }
    const entry = byGroup.get(node.group);
    const updated = node.subgroup === null
      ? { ...entry, own: node }
      : { ...entry, subgroups: [...entry.subgroups, node] };
    byGroup.set(node.group, updated);
  }
  return order.map((group) => {
    const entry = byGroup.get(group);
    const all = [entry.own, ...entry.subgroups].filter(Boolean);
    return {
      ...entry,
      count: all.reduce((sum, node) => sum + node.count, 0),
      newCount: all.reduce((sum, node) => sum + node.new_count, 0),
    };
  });
}

export function selectablePlaces(nodes) {
  return nodes.map((node) => placeOf(node.group, node.subgroup));
}

export function initialPlace(nodes, remembered) {
  const places = selectablePlaces(nodes);
  const kept = remembered && places.find((place) => samePlace(place, remembered));
  if (kept) return kept;
  const busy = nodes.find((node) => node.count > 0);
  return busy ? placeOf(busy.group, busy.subgroup) : places[0] || placeOf("", null);
}

export function groupHeadPlace(entry) {
  if (entry.own) return placeOf(entry.group, null);
  const first = entry.subgroups.find((node) => node.count > 0) || entry.subgroups[0];
  return placeOf(entry.group, first ? first.subgroup : null);
}
