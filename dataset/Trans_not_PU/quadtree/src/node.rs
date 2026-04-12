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
pub fn quadtree_node_isleaf(node: Option<&QuadtreeNode>) -> bool {
    match node {
        Some(n) => n.point.is_some(),
        None => false,
    }
}
pub fn quadtree_node_with_bounds(minx: f64, miny: f64, maxx: f64, maxy: f64) -> Option<Box<QuadtreeNode>> {
    // Attempt to create a new QuadtreeNode
    let mut node = quadtree_node_new()?;
    // Attempt to create new bounds for the node
    let mut bounds = quadtree_bounds_new()?;
    // Extend the bounds with the provided coordinates
    quadtree_bounds_extend(Some(&mut bounds), maxx, maxy);
    quadtree_bounds_extend(Some(&mut bounds), minx, miny);
    // Assign the bounds to the node
    node.bounds = Some(bounds);
    // Return the constructed node
    Some(node)
}
pub fn quadtree_node_ispointer(node: Option<&QuadtreeNode>) -> bool {
    node.map_or(false, |n| {
        n.nw.is_some()
            && n.ne.is_some()
            && n.sw.is_some()
            && n.se.is_some()
            && !quadtree_node_isleaf(Some(n))
    })
}
pub fn quadtree_node_isempty(node: Option<&QuadtreeNode>) -> bool {
    if let Some(node) = node {
        node.nw.is_none()
            && node.ne.is_none()
            && node.sw.is_none()
            && node.se.is_none()
            && !quadtree_node_isleaf(Some(node))
    } else {
        false
    }
}
pub fn quadtree_node_reset(
    node: Option<&QuadtreeNode>, 
    key_free: Option<&dyn Fn(&dyn std::any::Any)>
) {
    if let (Some(node), Some(key_free)) = (node, key_free) {
        if let Some(ref key) = node.key {
            key_free(key.as_ref());
        }
    }
}