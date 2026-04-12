

use crate::*;
pub fn quadtree_walk(
    root: &mut QuadtreeNode,
    descent: &mut dyn FnMut(&mut QuadtreeNode),
    ascent: &mut dyn FnMut(&mut QuadtreeNode),
) {
    descent(root);
    if let Some(ref mut nw) = root.nw {
        quadtree_walk(nw, descent, ascent);
    }
    if let Some(ref mut ne) = root.ne {
        quadtree_walk(ne, descent, ascent);
    }
    if let Some(ref mut sw) = root.sw {
        quadtree_walk(sw, descent, ascent);
    }
    if let Some(ref mut se) = root.se {
        quadtree_walk(se, descent, ascent);
    }
    ascent(root);
}
pub fn node_contains(outer: &QuadtreeNode, it: &QuadtreePoint) -> bool {
    if let Some(bounds) = &outer.bounds {
        if let (Some(nw), Some(se)) = (&bounds.nw, &bounds.se) {
            return nw.x < it.x && nw.y > it.y && se.x > it.x && se.y < it.y;
        }
    }
    false
}
pub fn get_quadrant<'a>(root: &'a QuadtreeNode, point: &QuadtreePoint) -> Option<&'a QuadtreeNode> {
    if let Some(ref nw) = root.nw {
        if node_contains(nw, point) {
            return Some(nw);
        }
    }
    if let Some(ref ne) = root.ne {
        if node_contains(ne, point) {
            return Some(ne);
        }
    }
    if let Some(ref sw) = root.sw {
        if node_contains(sw, point) {
            return Some(sw);
        }
    }
    if let Some(ref se) = root.se {
        if node_contains(se, point) {
            return Some(se);
        }
    }
    None
}
pub fn quadtree_new(minx: f64, miny: f64, maxx: f64, maxy: f64) -> Option<Box<Quadtree>> {
    let mut tree = Box::new(Quadtree {
        root: None,
        key_free: None,
        length: 0,
    });
    tree.root = quadtree_node_with_bounds(minx, miny, maxx, maxy);
    if tree.root.is_none() {
        return None;
    }
    Some(tree)
}
pub fn find(node: &QuadtreeNode, x: f64, y: f64) -> Option<&QuadtreePoint> {
    if quadtree_node_isleaf(node) {
        if let Some(point) = &node.point {
            if point.x == x && point.y == y {
                return Some(point);
            }
        }
    } else {
        let test = QuadtreePoint { x, y };
        if let Some(quadrant) = get_quadrant(node, &test) {
            return find(quadrant, x, y);
        }
    }
    None
}
pub fn insert_(
    key_free: Option<&fn(*mut std::ffi::c_void)>,
    root: &mut QuadtreeNode,
    point: &QuadtreePoint,
    key: Option<Box<dyn std::any::Any>>,
) -> i32 {
    // Default return value
    0
}
pub fn split_node_(
    tree: &mut Quadtree,
    node: &mut QuadtreeNode,
) -> i32 {
    // Default return value
    0
}
pub fn quadtree_search(tree: &Quadtree, x: f64, y: f64) -> Option<&QuadtreePoint> {
    match &tree.root {
        Some(root) => find(root, x, y),
        None => None,
    }
}
pub fn quadtree_insert(tree: &mut Quadtree, x: f64, y: f64, key: Option<Box<dyn std::any::Any>>) -> i32 {
    // Attempt to create a new QuadtreePoint
    let point = match quadtree_point_new(x, y) {
        Some(p) => p,
        None => return 0, // Return 0 if point creation fails
    };
    // Check if the point is contained within the root node
    if let Some(root) = &tree.root {
        if !node_contains(root, &point) {
            return 0; // Return 0 if the point is not contained
        }
    } else {
        return 0; // Return 0 if the tree has no root
    }
    // Attempt to insert the point into the tree
    if let Some(root) = &mut tree.root {
        if insert_(tree.key_free.as_ref(), root, &point, key) == 0 {
            return 0; // Return 0 if insertion fails
        }
    } else {
        return 0; // Return 0 if the tree has no root
    }
    // Increment the tree's length
    tree.length += 1;
    // Return 1 to indicate success
    1
}
