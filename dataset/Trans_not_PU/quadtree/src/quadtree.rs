use crate::*;
pub fn quadtree_walk(
    root: Option<&QuadtreeNode>,
    descent: Option<&dyn Fn(&QuadtreeNode)>,
    ascent: Option<&dyn Fn(&QuadtreeNode)>,
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
            if let (Some(nw), Some(se)) = (&bounds.nw, &bounds.se) {
                return nw.x < it_point.x && nw.y > it_point.y && se.x > it_point.x && se.y < it_point.y;
            }
        }
    }
    false
}
pub fn get_quadrant_<'a>(
    root: Option<&'a mut QuadtreeNode>, 
    point: Option<&QuadtreePoint>
) -> Option<&'a mut QuadtreeNode> {
    if let Some(root_node) = root {
        if node_contains_(root_node.nw.as_deref(), point) {
            return root_node.nw.as_deref_mut();
        }
        if node_contains_(root_node.ne.as_deref(), point) {
            return root_node.ne.as_deref_mut();
        }
        if node_contains_(root_node.sw.as_deref(), point) {
            return root_node.sw.as_deref_mut();
        }
        if node_contains_(root_node.se.as_deref(), point) {
            return root_node.se.as_deref_mut();
        }
    }
    None
}
pub fn quadtree_new<'a>(minx: f64, miny: f64, maxx: f64, maxy: f64) -> Option<Box<Quadtree<'a>>> {
    let root = quadtree_node_with_bounds(minx, miny, maxx, maxy)?;
    Some(Box::new(Quadtree {
        root: Some(root),
        key_free: None,
        length: 0,
    }))
}
pub fn reset_node_(tree: Option<&Quadtree>, node: Option<&QuadtreeNode>) {
    if let Some(_) = tree.and_then(|t| t.key_free.as_ref()) {
        quadtree_node_reset(node, None);
    } else {
        quadtree_node_reset(node, None);
    }
}
pub fn find_(node: Option<&QuadtreeNode>, x: f64, y: f64) -> Option<&QuadtreePoint> {
    if let Some(node_ref) = node {
        if quadtree_node_isleaf(Some(node_ref)) {
            if let Some(point) = &node_ref.point {
                if point.x == x && point.y == y {
                    return Some(point);
                }
            }
        } else {
            let test = QuadtreePoint { x, y };
            if let Some(next_node) = get_quadrant_(None, Some(&test)) {
                return find_(Some(next_node), x, y);
            }
        }
    }
    None
}
pub fn insert_(
    tree: Option<&Quadtree>,
    root: Option<&mut QuadtreeNode>,
    point: Option<Box<QuadtreePoint>>,
    key: Option<Box<dyn std::any::Any>>,
) -> i32 {
    if let Some(root_node) = root {
        if quadtree_node_isempty(Some(root_node)) {
            root_node.point = point;
            root_node.key = key;
            return 1;
        } else if quadtree_node_isleaf(Some(root_node)) {
            if let Some(root_point) = &root_node.point {
                if let Some(new_point) = &point {
                    if root_point.x == new_point.x && root_point.y == new_point.y {
                        reset_node_(tree, Some(root_node));
                        root_node.point = point;
                        root_node.key = key;
                        return 0;
                    }
                }
            }
            if split_node_(tree, Some(root_node)) == 0 {
                return 0;
            }
            return insert_(tree, Some(root_node), point, key);
        } else if quadtree_node_ispointer(Some(root_node)) {
            if let Some(quadrant) = get_quadrant_(Some(root_node), point.as_ref().map(|v| &**v)) {
                return insert_(tree, Some(quadrant), point, key);
            }
            return 0;
        }
    }
    0
}
pub fn split_node_(
    tree: Option<&Quadtree>,
    node: Option<&mut QuadtreeNode>,
) -> i32 {
    if let Some(node_ref) = node {
        if let Some(bounds) = &node_ref.bounds {
            if let Some(nw_point) = &bounds.nw {
                let x = nw_point.x;
                let y = nw_point.y;
                let hw = bounds.width / 2.0;
                let hh = bounds.height / 2.0;
                let nw = quadtree_node_with_bounds(x, y - hh, x + hw, y);
                let ne = quadtree_node_with_bounds(x + hw, y - hh, x + hw * 2.0, y);
                let sw = quadtree_node_with_bounds(x, y - hh * 2.0, x + hw, y - hh);
                let se = quadtree_node_with_bounds(x + hw, y - hh * 2.0, x + hw * 2.0, y - hh);
                if nw.is_none() || ne.is_none() || sw.is_none() || se.is_none() {
                    return 0;
                }
                node_ref.nw = nw;
                node_ref.ne = ne;
                node_ref.sw = sw;
                node_ref.se = se;
                let old_point = node_ref.point.take();
                let old_key = node_ref.key.take();
                return insert_(tree, Some(node_ref), old_point, old_key);
            }
        }
    }
    0
}
pub fn quadtree_search<'a>(tree: Option<&'a Quadtree>, x: f64, y: f64) -> Option<&'a QuadtreePoint> {
    find_(tree.and_then(|t| t.root.as_deref()), x, y)
}
pub fn quadtree_insert(
    tree: Option<&mut Quadtree>, 
    x: f64, 
    y: f64, 
    key: Option<&dyn Any>
) -> i32 {
    // Default return value for i32
    0
}