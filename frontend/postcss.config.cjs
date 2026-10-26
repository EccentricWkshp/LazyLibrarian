// As Sonarr's: nesting, and the breakpoints from breakpoints.css as custom media queries

const path = require('path');

module.exports = {
  plugins: {
    '@csstools/postcss-global-data': {
      files: [path.join(__dirname, 'src/Styles/Variables/breakpoints.css')],
    },
    'postcss-custom-media': {},
    'postcss-nested': {},
    autoprefixer: {},
  },
};
