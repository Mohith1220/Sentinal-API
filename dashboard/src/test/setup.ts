import '@testing-library/jest-dom';

// Mock SVG properties that jsdom doesn't support but D3 needs
if (typeof SVGElement !== 'undefined') {
  // Mock getBBox for SVG elements
  SVGElement.prototype.getBBox = function() {
    return {
      x: 0,
      y: 0,
      width: 100,
      height: 100,
      top: 0,
      right: 100,
      bottom: 100,
      left: 0,
      toJSON: () => ({}),
    };
  };

  // Mock getScreenCTM for SVG elements (needed by D3 zoom)
  SVGElement.prototype.getScreenCTM = function() {
    return {
      a: 1,
      b: 0,
      c: 0,
      d: 1,
      e: 0,
      f: 0,
      inverse: () => null,
      multiply: () => null,
      translate: () => null,
      scale: () => null,
      rotate: () => null,
      rotateFromVector: () => null,
      flipX: () => null,
      flipY: () => null,
      skewX: () => null,
      skewY: () => null,
    } as unknown as DOMMatrix;
  };

  // Mock createSVGPoint for SVG elements (needed by D3 zoom)
  if (typeof SVGSVGElement !== 'undefined') {
    SVGSVGElement.prototype.createSVGPoint = function() {
      return {
        x: 0,
        y: 0,
        matrixTransform: () => ({ x: 0, y: 0 }),
      } as unknown as DOMPoint;
    };
  }
}
