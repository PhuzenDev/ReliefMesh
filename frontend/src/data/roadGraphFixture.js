// data/road_graph.json ships as a backend fixture (loaded by
// GeoAgent.load_from_files) but GET /geo/state only returns road_status
// (id -> open/degraded/blocked), not node coordinates — there's no route
// geometry in the API today. This mirrors the same fixture client-side
// purely so the situation map has line geometry to color by live status.
// If /geo/state ever starts returning the graph, drop this in favor of
// that response.
import graph from "./road_graph.fixture.json";

export const roadGraphNodes = graph.nodes;
export const roadGraphEdges = graph.edges;
