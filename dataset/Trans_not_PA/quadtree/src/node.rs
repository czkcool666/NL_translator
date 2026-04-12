use crate::*;
pub fn quadtree_node_new() -> Option<Box<QuadtreeNode>> {
    Some(Box::new(QuadtreeNode {
        ne: None,
        nw: None,
        se: None,
        sw: None,
        bounds: None,
        point: None,
        key: None,
    }))
}
pub fn quadtree_node_isleaf(node: &QuadtreeNode) -> bool {
    node.point.is_some()
}
pub fn quadtree_node_with_bounds(minx: f64, miny: f64, maxx: f64, maxy: f64) -> Option<Box<QuadtreeNode>> {
    let mut node = quadtree_node_new()?;
    let mut bounds = quadtree_bounds_new()?;
    quadtree_bounds_extend(&mut bounds, maxx, maxy);
    quadtree_bounds_extend(&mut bounds, minx, miny);
    node.bounds = Some(Box::new(bounds));
    Some(node)
}
pub fn quadtree_node_ispointer(node: &QuadtreeNode) -> bool {
    node.nw.is_some()
        && node.ne.is_some()
        && node.sw.is_some()
        && node.se.is_some()
        && !quadtree_node_isleaf(node)
}
pub fn quadtree_node_isempty(node: &QuadtreeNode) -> bool {
    node.nw.is_none()
        && node.ne.is_none()
        && node.sw.is_none()
        && node.se.is_none()
        && !quadtree_node_isleaf(node)
}
pub fn quadtree_node_reset(node: &mut QuadtreeNode, key_free: fn(*mut std::ffi::c_void)) {
    if let Some(key) = node.key.take() {
        key_free(Box::into_raw(key) as *mut std::ffi::c_void);
    }
}