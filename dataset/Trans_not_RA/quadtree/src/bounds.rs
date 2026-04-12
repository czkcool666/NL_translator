use crate::*;
pub fn quadtree_bounds_new<'a>() -> Option<Box<QuadtreeBounds<'a>>> {
    let bounds = Box::new(QuadtreeBounds {
        nw: quadtree_point_new(f64::INFINITY, -f64::INFINITY)
            .map(|point| Box::leak(point) as &'a QuadtreePoint),
        se: quadtree_point_new(-f64::INFINITY, f64::INFINITY)
            .map(|point| Box::leak(point) as &'a QuadtreePoint),
        width: 0.0,
        height: 0.0,
    });
    Some(bounds)
}
pub fn quadtree_bounds_extend(
    bounds: Option<&mut QuadtreeBounds>,
    x: f64,
    y: f64,
) {
    todo!("Implementation ....");
}