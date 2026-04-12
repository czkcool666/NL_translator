#[derive(Debug, Clone, Copy, PartialEq)]
pub struct QuadtreePoint {
    pub x: f64,
    pub y: f64,
}
pub struct QuadtreeBounds {
    pub nw: Option<Box<QuadtreePoint>>,
    pub se: Option<Box<QuadtreePoint>>,
    pub width: f64,
    pub height: f64,
}
pub struct QuadtreeNode {
    pub ne: Option<Box<QuadtreeNode>>,
    pub nw: Option<Box<QuadtreeNode>>,
    pub se: Option<Box<QuadtreeNode>>,
    pub sw: Option<Box<QuadtreeNode>>,
    pub bounds: Option<Box<QuadtreeBounds>>,
    pub point: Option<Box<QuadtreePoint>>,
    pub key: Option<Box<dyn std::any::Any>>,
}
pub struct Quadtree {
    pub root: Option<Box<QuadtreeNode>>,
    pub key_free: Option<fn(*mut std::ffi::c_void)>,
    pub length: u32,
}