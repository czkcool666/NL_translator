// Translated Rust Code
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct QuadtreePoint {
    pub x: f64,
    pub y: f64,
}
// Translation of the C struct `quadtree_bounds` into Rust
pub struct QuadtreeBounds {
    // Nullable and Owning pointer in C translates to `Option<Box<T>>` in Rust for safe memory management.
    pub nw: Option<Box<QuadtreePoint>>,
    pub se: Option<Box<QuadtreePoint>>,
    pub width: f64,
    pub height: f64,
}
pub struct QuadtreeNode {
    pub ne: Option<Box<QuadtreeNode>>, // Nullable and Owning pointer in C translates to Option<Box<T>> in Rust
    pub nw: Option<Box<QuadtreeNode>>, // Nullable and Owning pointer in C translates to Option<Box<T>> in Rust
    pub se: Option<Box<QuadtreeNode>>, // Nullable and Owning pointer in C translates to Option<Box<T>> in Rust
    pub sw: Option<Box<QuadtreeNode>>, // Nullable and Owning pointer in C translates to Option<Box<T>> in Rust
    pub bounds: Option<Box<QuadtreeBounds>>, // Nullable and Owning pointer in C translates to Option<Box<T>> in Rust
    pub point: Option<Box<QuadtreePoint>>, // Nullable and Owning pointer in C translates to Option<Box<T>> in Rust
    pub key: Option<Box<dyn std::any::Any>>, // Nullable and Owning pointer in C translates to Option<Box<T>> in Rust. Using `dyn std::any::Any` for a generic key type.
}
pub struct Quadtree<'a> {
    pub root: Option<Box<QuadtreeNode>>, // Nullable and Owning pointer in C translates to Option<Box<T>> in Rust
    pub key_free: Option<&'a mut dyn FnMut(&mut dyn std::any::Any)>, // Nullable, Borrowed, and Mutable pointer with lifetime annotation
    pub length: u32, // `unsigned int` in C translates to `u32` in Rust
}