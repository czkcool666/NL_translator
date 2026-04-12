use crate::*;
pub fn quadtree_point_new(x: f64, y: f64) -> Option<QuadtreePoint> {
    Some(QuadtreePoint { x, y })
}