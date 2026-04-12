#[derive(Debug, Clone, Copy, PartialEq)]
pub struct QuadtreePoint {
    pub x: f64,
    pub y: f64,
}
pub struct QuadtreeBounds<'a> {
    pub nw: Option<&'a QuadtreePoint>, // Nullable pointer translated to Option<&QuadtreePoint>
    pub se: Option<&'a QuadtreePoint>, // Nullable pointer translated to Option<&QuadtreePoint>
    pub width: f64,
    pub height: f64,
}
pub struct QuadtreeNode<'a> {
    pub ne: Option<Box<QuadtreeNode<'a>>>, // Nullable pointer translated to Option<Box<QuadtreeNode>>
    pub nw: Option<Box<QuadtreeNode<'a>>>, // Nullable pointer translated to Option<Box<QuadtreeNode>>
    pub se: Option<Box<QuadtreeNode<'a>>>, // Nullable pointer translated to Option<Box<QuadtreeNode>>
    pub sw: Option<Box<QuadtreeNode<'a>>>, // Nullable pointer translated to Option<Box<QuadtreeNode>>
    pub bounds: Option<Box<QuadtreeBounds<'a>>>, // Nullable pointer translated to Option<Box<QuadtreeBounds>>
    pub point: Option<Box<QuadtreePoint>>, // Nullable pointer translated to Option<Box<QuadtreePoint>>
    pub key: Option<Box<dyn std::any::Any>>, // Nullable void pointer translated to Option<Box<dyn std::any::Any>>
}
pub struct Quadtree<'a> {
    pub root: Option<Box<QuadtreeNode<'a>>>, // Nullable pointer translated to Option<Box<QuadtreeNode>>
    pub key_free: Option<Box<dyn FnMut(&mut dyn std::any::Any) + 'a>>, // Nullable function pointer translated to Option<Box<dyn FnMut>>
    pub length: u32, // Unsigned int translated to u32
}