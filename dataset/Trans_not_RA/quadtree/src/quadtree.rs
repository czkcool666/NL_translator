use std::any::Any;
use crate::*;
pub fn quadtree_walk<'a>(
    root: Option<&'a QuadtreeNode<'a>>,
    descent: Option<&dyn Fn(&QuadtreeNode<'a>)>,
    ascent: Option<&dyn Fn(&QuadtreeNode<'a>)>,
) {
    if let Some(node) = root {
        if let Some(descent_fn) = descent {
            descent_fn(node);
        }
        if let Some(nw) = node.nw.as_deref() {
            quadtree_walk(Some(nw), descent, ascent);
        }
        if let Some(ne) = node.ne.as_deref() {
            quadtree_walk(Some(ne), descent, ascent);
        }
        if let Some(sw) = node.sw.as_deref() {
            quadtree_walk(Some(sw), descent, ascent);
        }
        if let Some(se) = node.se.as_deref() {
            quadtree_walk(Some(se), descent, ascent);
        }
        if let Some(ascent_fn) = ascent {
            ascent_fn(node);
        }
    }
}
pub fn node_contains_(outer: Option<&QuadtreeNode>, it: Option<&QuadtreePoint>) -> bool {
    if let (Some(outer_node), Some(it_point)) = (outer, it) {
        if let Some(bounds) = &outer_node.bounds {
            if let (Some(nw), Some(se)) = (bounds.nw, bounds.se) {
                return nw.x < it_point.x && nw.y > it_point.y && se.x > it_point.x && se.y < it_point.y;
            }
        }
    }
    false
}
pub fn get_quadrant_<'a>(
    root: Option<&'a QuadtreeNode<'a>>,
    point: Option<&'a QuadtreePoint>,
) -> Option<&'a QuadtreeNode<'a>> {
    if let Some(root_node) = root {
        if node_contains_(root_node.nw.as_deref(), point) {
            return root_node.nw.as_deref();
        }
        if node_contains_(root_node.ne.as_deref(), point) {
            return root_node.ne.as_deref();
        }
        if node_contains_(root_node.sw.as_deref(), point) {
            return root_node.sw.as_deref();
        }
        if node_contains_(root_node.se.as_deref(), point) {
            return root_node.se.as_deref();
        }
    }
    None
}
pub fn quadtree_new<'a>(minx: f64, miny: f64, maxx: f64, maxy: f64) -> Option<Box<Quadtree<'a>>> {
    // Attempt to allocate a new Quadtree instance
    let mut tree = Box::new(Quadtree {
        root: None,
        key_free: None,
        length: 0,
    });
    // Initialize the root node with the given bounds
    tree.root = quadtree_node_with_bounds(minx, miny, maxx, maxy);
    // If root initialization fails, return None
    if tree.root.is_none() {
        return None;
    }
    // Return the successfully created Quadtree wrapped in a Box
    Some(tree)
}
pub fn reset_node_<'a>(
    tree: Option<&mut Quadtree<'a>>, 
    node: Option<&mut QuadtreeNode<'a>>
) {
    if let Some(tree_ref) = tree {
        if tree_ref.key_free.is_some() {
            // Placeholder for logic if `key_free` is not None
        } else {
            // Placeholder for logic if `key_free` is None
        }
    } else {
        // Placeholder for logic if `tree` is None
    }
}
pub fn find_<'a>(
    node: Option<&'a QuadtreeNode<'a>>, 
    x: f64, 
    y: f64
) -> Option<&'a QuadtreePoint> {
    None
}
// Importing the `Any` trait to resolve the error
pub fn insert_<'a>(
    tree: Option<&'a Quadtree<'a>>, // Immutable access to `tree`
    root: Option<&'a mut QuadtreeNode<'a>>, // Mutable access to `root`
    point: Option<&'a QuadtreePoint>, // Nullable pointer to `QuadtreePoint`
    key: Option<Box<dyn Any>>, // Nullable void pointer translated to Option<Box<dyn Any>>
) -> i32 {
    // Default return value
    0
}
pub fn split_node_<'a>(
    tree: Option<&'a Quadtree<'a>>, // Nullable pointer to `Quadtree`
    node: Option<&'a mut QuadtreeNode<'a>>, // Nullable pointer to `QuadtreeNode`
) -> i32 {
    // Default return value
    0
}
pub fn quadtree_search<'a>(tree: Option<&'a Quadtree<'a>>, x: f64, y: f64) -> Option<&'a QuadtreePoint> {
    tree.and_then(|t| find_(t.root.as_deref(), x, y))
}
pub fn quadtree_insert(
    tree: Option<&mut Quadtree>, // Nullable pointer to `Quadtree`
    x: f64,                     // Double translated to f64
    y: f64,                     // Double translated to f64
    key: Option<Box<dyn Any>>,  // Nullable void pointer translated to Option<Box<dyn Any>>
) -> i32 {
    // Default return value for i32
    0
}