const API_URL = 'http://localhost:8000/api/statcast';

// Set up the visualization
const margin = { top: 20, right: 30, bottom: 40, left: 50 };
const width = 800 - margin.left - margin.right;
const height = 500 - margin.top - margin.bottom;

// Create SVG container
const svg = d3.select('#visualization')
    .append('svg')
    .attr('width', width + margin.left + margin.right)
    .attr('height', height + margin.top + margin.bottom)
    .append('g')
    .attr('transform', `translate(${margin.left},${margin.top})`);

// Create tooltip
const tooltip = d3.select('body')
    .append('div')
    .attr('class', 'tooltip')
    .style('opacity', 0);

// Fetch and visualize data
async function visualizeData() {
    try {
        const response = await fetch(API_URL);
        const data = await response.json();

        // Create scales
        const xScale = d3.scaleLinear()
            .domain([d3.min(data, d => d.launch_speed), d3.max(data, d => d.launch_speed)])
            .range([0, width]);

        const yScale = d3.scaleLinear()
            .domain([d3.min(data, d => d.launch_angle), d3.max(data, d => d.launch_angle)])
            .range([height, 0]);

        // Add axes
        svg.append('g')
            .attr('transform', `translate(0,${height})`)
            .call(d3.axisBottom(xScale))
            .append('text')
            .attr('class', 'axis-label')
            .attr('x', width)
            .attr('y', -6)
            .text('Exit Velocity (mph)');

        svg.append('g')
            .call(d3.axisLeft(yScale))
            .append('text')
            .attr('class', 'axis-label')
            .attr('transform', 'rotate(-90)')
            .attr('y', 6)
            .attr('dy', '.71em')
            .text('Launch Angle (degrees)');

        // Add scatter plot
        svg.selectAll('circle')
            .data(data)
            .enter()
            .append('circle')
            .attr('cx', d => xScale(d.launch_speed))
            .attr('cy', d => yScale(d.launch_angle))
            .attr('r', 5)
            .style('fill', '#134A8E')
            .style('opacity', 0.6)
            .on('mouseover', function(event, d) {
                tooltip.transition()
                    .duration(200)
                    .style('opacity', .9);
                tooltip.html(`Player: ${d.player_name}<br/>
                            Exit Velocity: ${d.launch_speed} mph<br/>
                            Launch Angle: ${d.launch_angle}°`)
                    .style('left', (event.pageX + 10) + 'px')
                    .style('top', (event.pageY - 28) + 'px');
            })
            .on('mouseout', function() {
                tooltip.transition()
                    .duration(500)
                    .style('opacity', 0);
            });

    } catch (error) {
        console.error('Error fetching data:', error);
    }
}

// Initialize visualization
visualizeData(); 